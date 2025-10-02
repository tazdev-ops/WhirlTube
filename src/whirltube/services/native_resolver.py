from __future__ import annotations
import httpx
from ..util import safe_httpx_proxy

def get_ios_hls(video_id: str, hl: str = "en", gl: str = "US", proxy: str | None = None) -> str | None:
    headers = {
        "User-Agent": "com.google.ios.youtube/20.03.02(iPhone16,2; U; CPU iOS 18_2_1 like Mac OS X; US)",
        "X-Goog-Api-Format-Version": "2",
        "Content-Type": "application/json",
    }
    ctx = {
        "context": {
            "client": {
                "clientName": "IOS",
                "clientVersion": "20.03.02",
                "hl": hl, "gl": gl,
                "deviceMake": "Apple",
                "deviceModel": "iPhone16,2",
                "osName": "iOS",
                "osVersion": "18.2.1.22C161",
                "utcOffsetMinutes": 0,
            },
            "request": {"useSsl": True, "internalExperimentFlags": []},
            "user": {"lockedSafetyMode": False},
        },
        "videoId": video_id,
        "contentCheckOk": True,
        "racyCheckOk": True,
    }
    url = "https://youtubei.googleapis.com/youtubei/v1/player?prettyPrint=false"
    
    proxies = {"all://": safe_httpx_proxy(proxy)} if proxy else None
    
    try:
        with httpx.Client(timeout=8.0, proxies=proxies) as c:
            r = c.post(url, headers=headers, json=ctx)
            r.raise_for_status()
            js = r.json()
            sd = js.get("streamingData") or {}
            hls = sd.get("hlsManifestUrl")
            return hls
    except Exception:
        return None
