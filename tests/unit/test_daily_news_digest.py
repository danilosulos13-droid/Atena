from scripts.daily_news_digest import NewsItem, format_digest, _category_allowed, _deduplicate_global, _is_santos_news


def test_format_digest_has_categories_links_and_disclaimer(tmp_path, monkeypatch):
    monkeypatch.setenv("ATENA_MEMORY_DB", str(tmp_path / "news.sqlite3"))
    message = format_digest(
        [NewsItem("Futebol", "Santos vence", "https://example.com/santos", "Fonte")],
        [],
        include_x=True,
    )
    assert "ATENA — principais notícias do dia" in message
    assert "<b>Futebol</b>" in message
    assert "https://example.com/santos" in message
    assert "matéria original" in message
    assert "Fonte: Fonte" in message
    assert "horário não informado" in message


def test_format_digest_reports_unavailable_sources():
    message = format_digest([], ["Fonte: Timeout"], include_x=False)
    assert "Fontes indisponíveis neste ciclo (1)" in message
    assert "Fonte: Timeout" in message


from xml.etree import ElementTree as ET

from scripts.daily_news_digest import _download_image, _open_graph_image, _rss_image_url, resolve_image_url


def test_rss_image_url_extracts_media_content():
    node = ET.fromstring(
        '<item xmlns:media="http://search.yahoo.com/mrss/"><media:content url="https://img.example/news.jpg" type="image/jpeg" /></item>'
    )
    assert _rss_image_url(node, "https://example.com/news") == "https://img.example/news.jpg"


def test_open_graph_image_accepts_both_meta_attribute_orders(monkeypatch):
    class Response:
        url = "https://news.example/story"
        headers = {"content-type": "text/html"}
        text = '<meta content="/image.jpg" property="og:image">'
        def raise_for_status(self):
            pass
    monkeypatch.setattr("scripts.daily_news_digest.requests.get", lambda *args, **kwargs: Response())
    assert _open_graph_image("https://news.example/story") == "https://news.example/image.jpg"


def test_download_image_rejects_non_image_content(monkeypatch):
    class Response:
        headers = {"content-type": "text/html"}
        content = b"not an image"
        def raise_for_status(self):
            pass
    monkeypatch.setattr("scripts.daily_news_digest.requests.get", lambda *args, **kwargs: Response())
    assert _download_image("https://news.example/image") is None


def test_resolve_image_url_rejects_non_http_image():
    item = NewsItem("Mundo", "Notícia", "https://example.com/news", "Fonte", image_url="file:///tmp/image.jpg")
    assert resolve_image_url(item, allow_open_graph=False) == ""


def test_global_deduplication_removes_same_story_across_categories():
    items = [
        NewsItem("Futebol", "Santos vence na Vila", "https://example.com/story", "ge"),
        NewsItem("Mundo", "Santos vence na Vila", "https://example.com/story", "BBC Brasil"),
    ]
    result = _deduplicate_global(items)
    assert len(result) == 1
    assert result[0].category == "Futebol"


def test_category_filter_rejects_sports_from_politics():
    assert _category_allowed(NewsItem("Política e Brasil", "Brasileirão tem rodada decisiva", "https://example.com/a", "Agência Brasil")) is False
    assert _category_allowed(NewsItem("Política e Brasil", "Congresso aprova nova lei", "https://example.com/b", "Agência Brasil")) is True


def test_science_filter_requires_relevant_title_for_agencia_brasil():
    assert _category_allowed(NewsItem("Ciência e IA", "Time vence campeonato", "https://example.com/a", "Agência Brasil")) is False
    assert _category_allowed(NewsItem("Ciência e IA", "Pesquisadores estudam física quântica", "https://example.com/b", "Agência Brasil")) is True


def test_santos_filter_rejects_unrelated_santos_mentions():
    assert _is_santos_news(NewsItem("Mundo", "Santos Dumont ganha exposição", "https://example.com/a", "BBC Brasil")) is False
    assert _is_santos_news(NewsItem("Futebol", "Santos FC anuncia novo reforço", "https://example.com/b", "ge")) is True


def test_santos_section_and_caption_are_personalized():
    from scripts.daily_news_digest import _caption, collect_santos

    source = NewsItem(
        "Futebol",
        "Santos vence na Vila Belmiro",
        "https://ge.example/santos",
        "ge",
        summary="O Peixe venceu e avançou.",
    )
    selected = collect_santos([source], limit=3)
    assert selected[0].category == "Santos FC"
    assert "torcida santista" in _caption(selected[0])


def test_configured_catalog_is_merged_without_duplicate_urls():
    from scripts.daily_news_digest import _merged_feeds

    feeds = _merged_feeds()
    urls = [url for sources in feeds.values() for _, url in sources]
    assert len(urls) >= 18
    assert len(urls) == len(set(urls))
    assert any(name == "The Verge" for sources in feeds.values() for name, _ in sources)
    assert any(name == "NASA Breaking News" for sources in feeds.values() for name, _ in sources)
    assert "Segurança digital" in feeds


def test_normalize_items_to_portuguese_translates_foreign_fields(monkeypatch):
    from scripts.daily_news_digest import normalize_items_to_portuguese

    translations = {
        "Global technology update": "Atualização global de tecnologia",
        "New tools improve artificial intelligence": "Novas ferramentas melhoram a inteligência artificial",
    }
    monkeypatch.setattr(
        "scripts.daily_news_digest._translate_to_portuguese",
        lambda value: translations.get(value, value),
    )
    errors = []
    items = [NewsItem(
        "Mundo", "Global technology update", "https://example.com/story", "Fonte",
        summary="New tools improve artificial intelligence",
    )]

    result = normalize_items_to_portuguese(items, errors)

    assert result[0].title == "Atualização global de tecnologia"
    assert result[0].summary.startswith("Novas ferramentas")
    assert errors == []


def test_normalize_items_to_portuguese_fails_closed_when_translation_fails(monkeypatch):
    from scripts.daily_news_digest import normalize_items_to_portuguese

    def fail(_value):
        raise ValueError("tradução não confirmada")

    monkeypatch.setattr("scripts.daily_news_digest._translate_to_portuguese", fail)
    errors = []
    items = [NewsItem("Mundo", "Foreign headline", "https://example.com/story", "Fonte")]

    result = normalize_items_to_portuguese(items, errors)

    assert result == []
    assert errors == ["tradução:Fonte:ValueError"]
