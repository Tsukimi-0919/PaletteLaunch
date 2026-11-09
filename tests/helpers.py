"""テスト用のファイル作成ヘルパー"""


def make_file(tmp_path, name, content="", encoding="utf-8"):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding=encoding)
    return str(p)


def make_url_file(tmp_path, url, name="game.url", encoding="utf-8", extra=""):
    return make_file(tmp_path, name,
                     f"[InternetShortcut]\nURL={url}\n{extra}", encoding=encoding)
