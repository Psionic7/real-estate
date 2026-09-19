import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class DataSourceError(ValueError):
    pass


def session():
    client = requests.Session()
    retry = Retry(total=3, backoff_factor=0.7, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"])
    client.mount("https://", HTTPAdapter(max_retries=retry))
    return client


def get(client, url, **kwargs):
    try:
        response = client.get(url, timeout=(5, 30), **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException:
        # requests exceptions may contain the full serviceKey URL: never expose it.
        raise DataSourceError("데이터 요청 실패: 네트워크·키·이용 승인·호출 한도를 확인하세요.") from None
