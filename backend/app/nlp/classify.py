"""Classification du type d'incident à partir de sa description (FR NLP).

TF-IDF (unigrammes + bigrammes) + régression logistique, comparé à un
baseline "classe majoritaire". Pas de transformer pré-entraîné : les
modèles Hugging Face ne sont pas téléchargeables depuis l'environnement
de développement (huggingface.co renvoie 403, cf. ADR-010).

Split aléatoire stratifié (et non temporel comme en ADR-009) : les
descriptions d'incidents sont des textes indépendants, sans dépendance
temporelle susceptible de créer une fuite entre train et test.
"""

from dataclasses import dataclass
from pathlib import Path

import joblib
import mlflow
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sqlalchemy.orm import Session

from app.ml.train import MLRUNS_DIR, MODELS_DIR
from app.models.silver import SilverIncident
from app.nlp.text import normalize_text

CLASSIFIER_PATH = MODELS_DIR / "incident_classifier.joblib"
AGGREGATE_KEYS = ("accuracy", "macro avg", "weighted avg")


@dataclass
class ClassifierResult:
    baseline_accuracy: float
    accuracy: float
    macro_f1: float
    per_class: dict
    train_size: int
    test_size: int
    model_path: Path


def _load_labeled_incidents(db: Session) -> tuple[list[str], list[str]]:
    rows = (
        db.query(SilverIncident.description, SilverIncident.incident_type)
        .filter(SilverIncident.description.isnot(None), SilverIncident.incident_type.isnot(None))
        .all()
    )
    return [normalize_text(d) for d, _ in rows], [t for _, t in rows]


def train_incident_classifier(db: Session) -> ClassifierResult:
    texts, labels = _load_labeled_incidents(db)
    if len(texts) < 50:
        raise ValueError(f"Pas assez d'incidents étiquetés pour entraîner ({len(texts)} < 50).")

    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels
    )

    baseline = DummyClassifier(strategy="most_frequent").fit(X_train, y_train)
    baseline_accuracy = accuracy_score(y_test, baseline.predict(X_test))

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
        ("clf", LogisticRegression(max_iter=1000)),
    ])
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)

    accuracy = accuracy_score(y_test, y_pred)
    macro_f1 = f1_score(y_test, y_pred, average="macro")
    report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)

    mlflow.set_tracking_uri(f"file://{MLRUNS_DIR}")
    mlflow.set_experiment("incident_type_classification")
    with mlflow.start_run(run_name="tfidf_logreg"):
        mlflow.log_params({"train_size": len(X_train), "test_size": len(X_test)})
        mlflow.log_metrics({
            "accuracy": accuracy, "macro_f1": macro_f1, "baseline_accuracy": baseline_accuracy,
        })

    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(pipeline, CLASSIFIER_PATH)

    return ClassifierResult(
        baseline_accuracy=round(float(baseline_accuracy), 4),
        accuracy=round(float(accuracy), 4),
        macro_f1=round(float(macro_f1), 4),
        per_class={k: v for k, v in report.items() if k not in AGGREGATE_KEYS},
        train_size=len(X_train),
        test_size=len(X_test),
        model_path=CLASSIFIER_PATH,
    )
