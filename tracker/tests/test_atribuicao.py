from rastro.atribuicao import achar_id_visita, niveis_meta, separar_nome_id


def test_separar_nome_id():
    assert separar_nome_id("Campanha [CBO] | Black|120210000000000001") == ("Campanha [CBO] | Black",
                                                                            "120210000000000001")
    assert separar_nome_id("120210000000000001") == (None, "120210000000000001")
    assert separar_nome_id("Campanha sem id") == ("Campanha sem id", None)
    assert separar_nome_id("Nome|abc") == ("Nome|abc", None)
    assert separar_nome_id(None) == (None, None)


def test_niveis_meta_no_padrao():
    niveis = niveis_meta({"utm_source": "FB", "utm_campaign": "C|111111", "utm_medium": "Conjunto|222222",
                          "utm_content": "Anúncio 1|333333", "utm_term": "Instagram_Reels"})
    assert niveis == {"campanha": ("C", "111111"), "conjunto": ("Conjunto", "222222"),
                      "anuncio": ("Anúncio 1", "333333")}


def test_niveis_meta_ignora_medium_generico_de_outras_fontes():
    niveis = niveis_meta({"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "Pesquisa",
                          "utm_content": "texto"})
    assert niveis == {"campanha": ("Pesquisa", None), "conjunto": (None, None), "anuncio": (None, None)}


def test_achar_id_visita():
    assert achar_id_visita({"sck": "tkabcdefghij0123456789"}) == "tkabcdefghij0123456789"
    assert achar_id_visita({"src": "TKABCDEFGHIJ0123456789"}) == "tkabcdefghij0123456789"
    assert achar_id_visita({"sck": "checkout-instagram"}) is None
