import ast
from pathlib import Path

VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"


def _revision(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "revision":
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
    raise AssertionError(f"No revision string found in {path}")


def test_alembic_revision_ids_fit_version_column() -> None:
    revisions = [_revision(path) for path in sorted(VERSIONS.glob("*.py"))]

    assert revisions
    assert len(revisions) == len(set(revisions))
    assert all(len(revision) <= 32 for revision in revisions)
