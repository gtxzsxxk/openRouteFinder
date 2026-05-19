from openRouterFinder.utils.validcode import generate_captcha_b64


def test_generate_captcha_b64():
    result = generate_captcha_b64(1234)
    assert result.startswith("data:image/jpeg;base64,")
    assert len(result) > 100
