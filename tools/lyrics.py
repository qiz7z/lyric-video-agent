"""歌词获取：MP3 内嵌 LRC（首选，与音频同版本零校准）→ LRCLib API（兜底）。

内嵌歌词优先的理由（SOP）：同一文件里的歌词必然和音频是同一版本，
省掉跨版本校准；酷我等来源的 USLT::zho 标签通常带完整 LRC。

已知坑（均在此处理）：
- 内嵌文本可能是 "LRC + awlrc base64" 混合体，base64 行必须过滤；
- [offset:±ms] 全局偏移要应用；
- 元数据行（[ti:][ar:][al:][by:] 及 "作词/作曲/编曲" 等无时间戳行）要过滤；
- 同一时刻完全重复的行要去重（重复行会导致字幕重复 + 结尾逻辑错乱）；
- 繁体用 opencc 转简体（opencc 缺失时原样保留，不阻塞）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
META_TAGS = re.compile(r"^\[(ti|ar|al|by|length|re|ve|hash|total|awlrc)[::]", re.I)
META_WORDS = re.compile(
    r"^(作词|作曲|编曲|填词|谱曲|演唱|原唱|制作|混音|和声|监制|出品|发行"
    r"|词|曲|编|吉他|贝斯|鼓)\s*[：:]"
)


def _t2s(text: str) -> str:
    """繁->简；opencc 未安装则原样返回。"""
    try:
        from opencc import OpenCC

        return OpenCC("t2s").convert(text)
    except Exception:
        return text


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """把任意 LRC 文本解析为 [(秒, 行文本)]，含 offset / 元数据 / 重复行处理。"""
    offset_ms = 0.0
    m = re.search(r"^\[offset:\s*([+-]?\d+)\s*\]", text, re.M | re.I)
    if m:
        offset_ms = float(m.group(1))

    out: list[tuple[float, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or META_TAGS.match(line):
            continue
        times = LRC_TIME.findall(line)
        if not times:
            # 无时间戳：过滤元数据词行，其余丢弃（无法对轴）
            if not META_WORDS.match(line):
                continue
            continue
        body = LRC_TIME.sub("", line).strip().strip("-— ").strip()
        if not body or body.startswith("awlrc"):
            continue
        # 带时间戳的制作信息行（词：xxx / 作曲：xxx）
        if META_WORDS.match(body):
            continue
        # base64 长串（酷我 awlrc 残留）过滤：非中文占比过高的超长行
        if len(body) > 120 and sum("\u4e00" <= ch <= "\u9fff" for ch in body) < 10:
            continue
        for mm, ss, frac in times:
            t = int(mm) * 60 + int(ss) + float("0." + frac) if frac else int(mm) * 60 + int(ss)
            out.append((t - offset_ms / 1000.0, body))

    out.sort(key=lambda x: x[0])
    # 去重：同一秒内文本完全相同的行只留一条
    dedup: list[tuple[float, str]] = []
    for t, s in out:
        if dedup and abs(t - dedup[-1][0]) < 0.6 and s == dedup[-1][1]:
            continue
        dedup.append((t, s))
    # 末尾重复行（LRC 源偶发 bug：末句在 10s 内原样再挂一次）会破坏结尾逻辑
    if len(dedup) >= 2 and dedup[-1][1] == dedup[-2][1] and dedup[-1][0] - dedup[-2][0] < 10:
        dedup.pop()
    return dedup


@dataclass
class Lyrics:
    title: str
    artist: str
    lines: list[tuple[float, str]] = field(default_factory=list)
    source: str = "none"  # embedded | lrclib | none
    raw: str = ""


def read_embedded_lrc(audio_path: str) -> str | None:
    """读 MP3/FLAC 内嵌歌词标签。USLT::zho 优先，其次任意 USLT / ©lyr。"""
    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return None
    mf = MutagenFile(audio_path)
    if mf is None or not mf.tags:
        return None
    # ID3（mp3）
    uslt = [k for k in mf.tags.keys() if k.startswith("USLT")]
    for key in sorted(uslt, key=lambda k: 0 if k.endswith("zho") else 1):
        frame = mf.tags.get(key)
        text = getattr(frame, "text", None)
        if text and "[" in text:
            return text
    # MP4（m4a）©lyr
    lyr = mf.tags.get("\xa9lyr")
    if lyr:
        return str(lyr[0])
    return None


def fetch_lrclib(title: str, artist: str, duration: float, album: str = "") -> str | None:
    """LRCLib 公开 API（无需 key）。直连通常可用；超时/失败静默返回 None。"""
    import requests

    for url, params in (
        (
            "https://lrclib.net/api/get",
            {
                "track_name": title,
                "artist_name": artist,
                "album_name": album,
                "duration": int(duration),
            },
        ),
        ("https://lrclib.net/api/search", {"track_name": title, "artist_name": artist}),
    ):
        try:
            r = requests.get(
                url, params=params, timeout=15, headers={"User-Agent": "LyricVideoAgent/1.0"}
            )
            if r.status_code != 200:
                continue
            data = r.json()
            items = data if isinstance(data, list) else [data]
            best = None
            for it in items:
                for k in ("syncedLyrics", "plainLyrics"):
                    if it.get(k):
                        best = best or it.get(k)
            if best:
                return best
        except Exception:
            continue
    return None


def load_lyrics(
    audio_path: str, title: str, artist: str = "", duration: float = 0.0, album: str = ""
) -> Lyrics:
    """入口：内嵌优先，LRCLib 兜底，繁转简。永不抛异常（source=none 表示拿不到）。

    title 允许直接传文件名风格 "歌名 - 歌手"（本工作区命名惯例），
    未显式给 artist 时自动拆分。
    """
    if not artist and " - " in title:
        title, artist = title.rsplit(" - ", 1)
        title, artist = title.strip(), artist.strip()
        # 歌手名可能还挂在文件尾部括号里（如 "郑源 (Jacky)"）
        artist = re.sub(r"[（(].*?[)）]", "", artist).strip()
    ly = Lyrics(title=title, artist=artist)
    raw = read_embedded_lrc(audio_path)
    if raw:
        ly.source = "embedded"
    elif duration:
        raw = fetch_lrclib(title, artist, duration, album)
        if raw:
            ly.source = "lrclib"
    ly.raw = raw or ""
    ly.lines = [(t, _t2s(s)) for t, s in parse_lrc(ly.raw)] if ly.raw else []
    # 内嵌 LRC 常把歌名/歌手做成 0 时刻的字幕卡：丢弃
    if ly.lines:
        head = ly.lines[0]
        if head[0] < 1.5 and (title in head[1] or (artist and artist in head[1])):
            ly.lines = ly.lines[1:]
    return ly


def save_raw(ly: Lyrics, out_path: str) -> None:
    """落盘为 `秒<TAB>文本`（工作区惯例格式，便于人工核对）。"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# source={ly.source} title={ly.title} artist={ly.artist}\n")
        for t, s in ly.lines:
            f.write(f"{t:.3f}\t{s}\n")
