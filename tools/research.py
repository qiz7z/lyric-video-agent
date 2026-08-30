# -*- coding: utf-8 -*-
"""歌曲调研工具：给封面 Agent 的"先理解这首歌"环节提供弹药。

三级信息源（全部免费、可独立失效）：
  1. web 搜索（ddgs / DuckDuckGo，直连实测可用）——百科/乐评/背景故事
  2. MusicBrainz 结构化元数据——艺人/专辑/发行年份/标签
  3. 本地 mp3 元数据（mutagen）——专辑/年份/流派
任何一级失败都不抛异常，聚合可用的部分；全失败返回空壳（上层走原流程）。
"""
from __future__ import annotations


def search_web(query: str, max_results: int = 5,
               proxies: dict | None = None) -> list[dict]:
    """网页搜索，返回 [{title, body, href}]。直连失败自动试代理。

    ddgs 9.x 的参数是构造器上的单数 proxy（字符串），传 proxies 字典会 TypeError。
    """
    from ddgs import DDGS

    def _as_proxy_str(px) -> str | None:
        if isinstance(px, dict):
            return px.get("http") or px.get("https")
        return px

    proxy_str = _as_proxy_str(proxies)
    attempts: list[str | None] = [None] + ([proxy_str] if proxy_str else [])
    last_err = None
    for px in attempts:
        try:
            ddgs = DDGS(proxy=px) if px else DDGS()
            rs = list(ddgs.text(query, max_results=max_results))
            return [{"title": r.get("title", "")[:100],
                     "body": r.get("body", "")[:300],
                     "href": r.get("href", "")} for r in rs]
        except Exception as e:
            last_err = e
            continue
    print(f"  [research] web 搜索失败: {type(last_err).__name__}: {str(last_err)[:100]}")
    return []


def musicbrainz_info(title: str, artist: str) -> dict | None:
    """MusicBrainz 录音检索（免费无 key，需 UA）。返回 {artist, releases, tags, length}。"""
    import requests
    try:
        q = f'recording:"{title}"'
        if artist:
            q += f' AND artist:"{artist}"'
        r = requests.get("https://musicbrainz.org/ws/2/recording",
                         params={"query": q, "fmt": "json", "limit": 3},
                         headers={"User-Agent": "LyricVideoAgent/1.0 (portfolio)"},
                         timeout=15)
        r.raise_for_status()
        recs = r.json().get("recordings") or []
        if not recs:
            return None
        rec = recs[0]
        artists = "、".join(a.get("name", "") for a in rec.get("artist-credit", []) if isinstance(a, dict))
        releases = list({rel.get("title", "") for rel in rec.get("releases", []) if rel.get("title")})[:3]
        dates = list({rel.get("date", "")[:4] for rel in rec.get("releases", []) if rel.get("date")})
        return {"recording": rec.get("title"), "artist": artists,
                "albums": releases, "years": dates,
                "tags": [t.get("name") for t in rec.get("tags", [])[:6]]}
    except Exception as e:
        print(f"  [research] MusicBrainz 失败: {type(e).__name__}: {str(e)[:100]}")
        return None


def local_meta(audio_path: str | None) -> dict:
    """mp3 自带元数据（专辑/年份/流派）。"""
    if not audio_path:
        return {}
    try:
        from mutagen import File as MutagenFile
        mf = MutagenFile(audio_path)
        if mf is None or not mf.tags:
            return {}
        def g(*keys):
            for k in keys:
                v = mf.tags.get(k)
                if v:
                    return str(v[0]) if isinstance(v, list) else str(v)
            return ""
        return {"album": g("\xa9alb", "TALB"), "date": g("\xa9day", "TDRC"),
                "genre": g("\xa9gen", "TCON")}
    except Exception:
        return {}


def research_package(title: str, artist: str,
                     audio_path: str | None = None,
                     proxies: dict | None = None) -> dict:
    """聚合三级信息源，交给 LLM 消化。永不抛异常。"""
    pkg = {"web": [], "musicbrainz": None, "local": {}}
    pkg["web"] = search_web(f"{title} {artist} 歌曲 背景 主题", proxies=proxies)
    pkg["musicbrainz"] = musicbrainz_info(title, artist)
    pkg["local"] = local_meta(audio_path)
    ok = bool(pkg["web"] or pkg["musicbrainz"] or pkg["local"])
    print(f"[research] 信息源: web {len(pkg['web'])} 条 | mb {'有' if pkg['musicbrainz'] else '无'} "
          f"| local {'有' if pkg['local'] else '无'}")
    return {**pkg, "ok": ok}
