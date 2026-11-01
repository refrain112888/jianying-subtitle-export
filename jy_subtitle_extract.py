"""
剪映字幕提取 —— 菜单版

从剪映加密草稿（draft_content.json）里提取全部文本/字幕，导出 SRT。

直接双击「提取字幕.bat」或运行本脚本：自动进入剪映草稿根目录，列出所有草稿，
输入序号回车即可导出对应字幕。输出到本脚本所在文件夹，文件名 = 草稿名.srt。

原理：密钥材料藏在密文本身 —— 在固定字符位置各取 4 个字符拼成 48 字节
      （前 32 字节 AES-256 key，后 16 字节 GCM IV），把这 12 段剔除后
      剩余 base64 解码即为密文，AES-256-GCM 解密得到明文 JSON。

依赖：cryptography
用法：python jy_subtitle_extract.py                # 菜单模式
      python jy_subtitle_extract.py "<草稿目录>"    # 直接提取指定草稿
"""

import base64
import json
import os
import re
import sys
import time
import unicodedata

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 剪映 11.x 的密钥切片位置（12 处，各取 4 字符）
KEY_POSITIONS = [0, 7, 20, 33, 40, 47, 59, 66, 76, 89, 99, 127]


# ---------- 路径定位 ----------

def draft_root() -> str:
    """剪映草稿根目录。用户名不写死，走系统环境变量。"""
    env = os.environ.get("JIANYING_DRAFT_ROOT", "").strip().strip('"')
    if env and os.path.isdir(env):
        return env
    local = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(local, "JianyingPro", "User Data",
                        "Projects", "com.lveditor.draft")


def list_drafts(root: str):
    """列出草稿目录（排除 . 开头的系统文件夹，必须含 draft_content.json）。"""
    found = []
    try:
        names = os.listdir(root)
    except OSError:
        return found
    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        content = os.path.join(path, "draft_content.json")
        if not os.path.isfile(content):
            continue
        found.append({"name": name, "path": path, "mtime": os.path.getmtime(content)})
    found.sort(key=lambda x: x["mtime"], reverse=True)
    return found


# ---------- 解密 ----------

def decrypt_draft_text(blob: str) -> str:
    """密文文本 -> 明文 JSON 文本"""
    blob = blob.strip()
    keymat = "".join(blob[p:p + 4] for p in KEY_POSITIONS).encode()
    if len(keymat) != 48:
        raise ValueError("文件长度不足以取出密钥材料")

    chars = list(blob)
    for p in sorted(KEY_POSITIONS, reverse=True):
        del chars[p:p + 4]
    cipher = base64.b64decode("".join(chars))

    plain = AESGCM(keymat[:32]).decrypt(keymat[32:], cipher, None)
    return plain.decode("utf-8")


def clean_text(raw: str) -> str:
    try:
        return str(json.loads(raw).get("text", "")).strip()
    except Exception:
        return re.sub(r"<[^>]+>", "", raw).replace("\\n", "\n").strip()


def to_srt_time(us: int) -> str:
    ms = int(round(us / 1000.0))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def collect_items(draft: dict):
    texts = {t["id"]: t for t in draft.get("materials", {}).get("texts", [])}
    items = []
    for track in draft.get("tracks", []):
        if track.get("type") != "text":
            continue
        for seg in track.get("segments", []):
            mat = texts.get(seg.get("material_id"))
            if not mat:
                continue
            body = clean_text(mat.get("content", ""))
            if not body:
                continue
            rng = seg.get("target_timerange") or {}
            start = rng.get("start", 0)
            items.append({"start": start, "end": start + rng.get("duration", 0), "text": body})
    items.sort(key=lambda x: x["start"])
    return items


# ---------- 提取 ----------

def extract(draft_dir: str, out: str = None) -> int:
    draft_dir = os.path.normpath(draft_dir)
    src = os.path.join(draft_dir, "draft_content.json")
    if not os.path.isfile(src):
        print(f"找不到 draft_content.json：\n  {src}")
        return 2

    name = os.path.basename(draft_dir.rstrip("\\/")) or "字幕"
    out = out or os.path.join(SCRIPT_DIR, f"{name}.srt")

    raw = open(src, encoding="utf-8").read()
    try:
        plain = decrypt_draft_text(raw) if not raw.lstrip().startswith("{") else raw
    except Exception as exc:
        print(f"解密失败（{type(exc).__name__}）。可能是剪映升级后换了加密方式。")
        return 3

    items = collect_items(json.loads(plain))
    if not items:
        print("这个草稿里没有文字/字幕轨道。")
        return 4

    lines = []
    for i, it in enumerate(items, 1):
        lines += [str(i), f"{to_srt_time(it['start'])} --> {to_srt_time(it['end'])}", it["text"], ""]

    with open(out, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(lines))
    print(f"✓ {len(items)} 条字幕 -> {out}")
    return 0


# ---------- 界面 ----------

def dwidth(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - dwidth(s))


def choose(root: str) -> int:
    drafts = list_drafts(root)
    if not drafts:
        print(f"这里没有找到草稿：\n  {root}")
        print("如果路径不对，可设置环境变量 JIANYING_DRAFT_ROOT 指向草稿根目录。")
        return 2

    width = max(dwidth(d["name"]) for d in drafts) + 2
    print()
    print(f"草稿目录：{root}")
    print(f"共 {len(drafts)} 个草稿\n")
    for i, d in enumerate(drafts, 1):
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["mtime"]))
        print(f"  {i:>2})  {pad(d['name'], width)}{stamp}")
    print()
    print("输入序号回车导出，可连续导出多个；0 = 全部；o 打开文件夹；q 退出")

    while True:
        try:
            raw = input("\n序号: ").strip()
        except (EOFError, KeyboardInterrupt):
            return 1
        if raw.lower() in ("q", "quit", "exit"):
            return 0
        if raw.lower() in ("o", "open"):
            try:
                os.startfile(root)
            except Exception:
                print(f"打不开：{root}")
            continue
        if raw == "0":
            total, ok = len(drafts), 0
            print()
            for i, d in enumerate(drafts, 1):
                print(f"[{i}/{total}] {d['name']}")
                if extract(d["path"]) == 0:
                    ok += 1
                print()
            print(f"全部完成：{ok}/{total} 个草稿导出成功 -> {SCRIPT_DIR}")
            continue
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(drafts):
                print()
                extract(drafts[idx - 1]["path"])
                continue
            print(f"序号要在 1 - {len(drafts)} 之间（0 表示全部）")
            continue
        print("请输入数字序号")


def main() -> int:
    arg = ""
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().strip('"').strip("'").strip()

    out = sys.argv[2] if len(sys.argv) > 2 else None

    if arg:
        path = os.path.normpath(arg)
        if os.path.isfile(os.path.join(path, "draft_content.json")):
            return extract(path, out)
        if os.path.isdir(path):
            return choose(path)
        print(f"路径不存在：{path}")
        return 2

    root = draft_root()
    if not os.path.isdir(root):
        print(f"没找到剪映草稿根目录：\n  {root}")
        try:
            typed = input("请粘贴草稿根目录后回车：").strip().strip('"').strip("'")
        except (EOFError, KeyboardInterrupt):
            return 1
        if not typed or not os.path.isdir(typed):
            return 2
        root = typed
    return choose(root)


if __name__ == "__main__":
    sys.exit(main())
