from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def assert_contains(source: str, needle: str, label: str) -> None:
    if needle not in source:
        raise AssertionError(f"Missing {label}: {needle}")


def main() -> None:
    new_template = read(TEMPLATES / "new.html")
    layout_template = read(TEMPLATES / "layout.html")
    styles = read(STATIC / "styles.css")

    assert_contains(new_template, 'list="cat-list"', "category existing-value source")
    assert_contains(new_template, 'list="loc-list"', "location existing-value source")
    assert_contains(new_template, 'list="bin-list"', "bin existing-value source")
    assert_contains(new_template, 'list="unit-list"', "unit existing-value source")

    assert_contains(layout_template, "enhanceDatalistInputs", "datalist enhancement entrypoint")
    assert_contains(layout_template, "querySelectorAll('input[list]')", "datalist input selection")
    assert_contains(layout_template, "escapeSelectorId", "selector id escaping")
    assert_contains(layout_template, "root.querySelector?.(`#${escapeSelectorId(listId)}`)", "scoped datalist lookup")
    assert_contains(layout_template, "mobile-combobox-option", "custom option rendering")
    assert_contains(layout_template, "body.querySelectorAll('input[type=\"date\"]')", "existing modal script block")
    assert_contains(layout_template, "enhanceDatalistInputs(body)", "modal datalist enhancement")

    assert_contains(styles, ".mobile-combobox", "combobox wrapper styles")
    assert_contains(styles, ".mobile-combobox-panel", "combobox option panel styles")
    assert_contains(styles, ".mobile-combobox-option", "combobox option styles")


if __name__ == "__main__":
    main()
