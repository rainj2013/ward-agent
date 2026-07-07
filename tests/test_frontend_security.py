from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_markdown_output_is_sanitized():
    html = (ROOT / "static/index.html").read_text()
    js = (ROOT / "static/js/security.js").read_text()
    assert "dompurify@3.1.6" in html
    assert "DOMPurify.sanitize" in js
    assert js.count("marked.parse") == 1


def test_runtime_page_uses_page_specific_script():
    html = (ROOT / "static/runtime.html").read_text()
    assert "/static/js/runtime.js" in html
    assert "/static/js/app.js" not in html
