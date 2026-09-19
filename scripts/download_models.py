"""下载识别与校对模型到 models/ 目录。

只用标准库——本脚本必须在 pip install 之前也能运行（安装链路的第一环）。
设计要点：
- 每个下载目标带多级 URL fallback（官方源 → 镜像源），单源失败自动换下一个
- 大文件断点续传（.part 文件 + Range 请求）
- 幂等：模型已就位则跳过；--force 强制重下
"""

from __future__ import annotations

import argparse
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"

# ---- 识别模型：sherpa-onnx 流式 Zipformer 中英双语 ----
ASR_NAME = "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
ASR_DIR = MODELS_DIR / "asr" / ASR_NAME
ASR_REQUIRED = (
    "encoder-epoch-99-avg-1.onnx",
    "decoder-epoch-99-avg-1.onnx",
    "joiner-epoch-99-avg-1.onnx",
    "tokens.txt",
)
# 主源：GitHub Release 整包；备源：ModelScope 镜像逐文件
ASR_TARBALL_URLS = (
    f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{ASR_NAME}.tar.bz2",
)
ASR_MS_BASE = (
    "https://modelscope.cn/models/pengzhendong/sherpa-onnx-streaming-zipformer-bilingual-zh-en/resolve/master"
)

# ---- 停顿标点：sherpa-onnx 中文/英文 CT-Transformer INT8 ----
PUNCT_NAME = "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
PUNCT_DIR = MODELS_DIR / "punctuation" / PUNCT_NAME
PUNCT_DEST = PUNCT_DIR / "model.int8.onnx"
PUNCT_MIN_BYTES = 70_000_000
PUNCT_TARBALL_URLS = (
    f"https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models/{PUNCT_NAME}.tar.bz2",
)
PUNCT_FILE_URLS = (
    f"https://modelscope.cn/models/csukuangfj/{PUNCT_NAME}/resolve/master/model.int8.onnx",
    f"https://huggingface.co/lorneluo/{PUNCT_NAME}/resolve/main/model.int8.onnx",
    f"https://hf-mirror.com/lorneluo/{PUNCT_NAME}/resolve/main/model.int8.onnx",
)

# ---- 校对模型：Qwen3-1.7B Q4_K_M GGUF（unsloth 量化版，官方仓只有 Q8_0）----
LLM_FILE = "Qwen3-1.7B-Q4_K_M.gguf"
LLM_DEST = MODELS_DIR / "llm" / LLM_FILE
LLM_MIN_BYTES = 1_000_000_000  # Q4_K_M 约 1.1GB，小于此值视为不完整
LLM_URLS = (
    f"https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/{LLM_FILE}",
    f"https://hf-mirror.com/unsloth/Qwen3-1.7B-GGUF/resolve/main/{LLM_FILE}",
    f"https://modelscope.cn/models/unsloth/Qwen3-1.7B-GGUF/resolve/master/{LLM_FILE}",
)

CHUNK = 1 << 20
UA = "voice2text-installer/0.1"


def _human(n: int) -> str:
    mb = n / (1 << 20)
    return f"{mb:.0f}MB" if mb < 1024 else f"{mb / 1024:.2f}GB"


def _progress(name: str, done: int, total: int | None, t0: float, base: int = 0) -> None:
    if total:
        pct = done * 100 // total
        speed = (done - base) / max(time.time() - t0, 0.1) / (1 << 20)
        sys.stdout.write(f"\r  {name}: {pct:3d}%  {_human(done)}/{_human(total)}  {speed:.1f}MB/s  ")
    else:
        sys.stdout.write(f"\r  {name}: {_human(done)}  ")
    sys.stdout.flush()


def download(urls: tuple[str, ...], dest: Path, min_bytes: int = 0) -> bool:
    """从多个候选 URL 依次尝试下载到 dest，支持断点续传。任一成功即返回 True。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size >= max(min_bytes, 1):
        print(f"  [跳过] {dest.name} 已存在（{_human(dest.stat().st_size)}）")
        return True

    part = dest.with_name(dest.name + ".part")
    for url in urls:
        try:
            resume = part.stat().st_size if part.is_file() else 0
            headers = {"User-Agent": UA}
            if resume:
                headers["Range"] = f"bytes={resume}-"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                length = resp.getheader("Content-Length")
                length = int(length) if length else None
                if resume and getattr(resp, "status", 200) == 200:
                    resume = 0  # 服务端不支持 Range，从头下
                total = (length + resume) if length is not None else None
                done, t0 = resume, time.time()
                with open(part, "ab" if resume else "wb") as f:
                    while True:
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        _progress(dest.name, done, total, t0, base=resume)
                sys.stdout.write("\n")
            size = part.stat().st_size
            if min_bytes and size < min_bytes:
                raise IOError(f"下载不完整: {size} < {min_bytes} 字节")
            if total is not None and size != total:
                raise IOError(f"大小不符: 实际 {size}，预期 {total}")
            part.replace(dest)
            print(f"  [完成] {dest.name}（{_human(size)}）")
            return True
        except Exception as exc:  # noqa: BLE001 —— 逐源 fallback，任何失败都换下一个源
            sys.stdout.write("\n")
            print(f"  [警告] 源不可用，换下一个：{exc}")
            continue
    print(f"  [失败] {dest.name} 所有下载源均不可用")
    return False


def install_asr(force: bool) -> bool:
    if not force and all((ASR_DIR / f).is_file() for f in ASR_REQUIRED):
        print("[asr] 模型已就绪，跳过")
        return True

    ASR_DIR.mkdir(parents=True, exist_ok=True)
    tarball = MODELS_DIR / "asr" / f"{ASR_NAME}.tar.bz2"
    if download(ASR_TARBALL_URLS, tarball):
        try:
            wanted = set(ASR_REQUIRED)
            with tarfile.open(tarball, "r:bz2") as tar:
                for member in tar.getmembers():
                    base = Path(member.name).name
                    if base in wanted and member.isfile():
                        member.name = base  # 抹平顶层目录，直接解到 ASR_DIR
                        tar.extract(member, ASR_DIR)
            tarball.unlink(missing_ok=True)  # 释放磁盘
        except Exception as exc:  # noqa: BLE001
            # 坏包必须清掉，否则下次重跑会被"已存在即跳过"逻辑永远跳过
            tarball.unlink(missing_ok=True)
            print(f"  [警告] 解压失败（{exc}），改用镜像逐文件下载")
    if all((ASR_DIR / f).is_file() for f in ASR_REQUIRED):
        print("[asr] 就绪")
        return True

    # fallback：ModelScope 逐文件
    print("[asr] 从 ModelScope 镜像逐文件下载")
    ok = True
    for name in ASR_REQUIRED:
        ok = download((f"{ASR_MS_BASE}/{name}",), ASR_DIR / name) and ok
    if ok:
        print("[asr] 就绪")
    return ok


def install_llm(force: bool) -> bool:
    if not force and LLM_DEST.is_file() and LLM_DEST.stat().st_size >= LLM_MIN_BYTES:
        print(f"[llm] 模型已就绪，跳过（{_human(LLM_DEST.stat().st_size)}）")
        return True
    if not download(LLM_URLS, LLM_DEST, min_bytes=LLM_MIN_BYTES):
        return False
    print("[llm] 就绪")
    return True


def install_punctuation(force: bool) -> bool:
    if not force and PUNCT_DEST.is_file() and PUNCT_DEST.stat().st_size >= PUNCT_MIN_BYTES:
        print(f"[punctuation] 模型已就绪，跳过（{_human(PUNCT_DEST.stat().st_size)}）")
        return True
    PUNCT_DIR.mkdir(parents=True, exist_ok=True)
    tarball = MODELS_DIR / "punctuation" / f"{PUNCT_NAME}.tar.bz2"
    if download(PUNCT_TARBALL_URLS, tarball):
        try:
            with tarfile.open(tarball, "r:bz2") as tar:
                member = next(
                    item for item in tar.getmembers()
                    if Path(item.name).name == "model.int8.onnx" and item.isfile()
                )
                member.name = "model.int8.onnx"
                tar.extract(member, PUNCT_DIR)
            tarball.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            tarball.unlink(missing_ok=True)
            print(f"  [警告] 标点模型解压失败（{exc}），改用镜像下载")
    if PUNCT_DEST.is_file() and PUNCT_DEST.stat().st_size >= PUNCT_MIN_BYTES:
        print("[punctuation] 就绪")
        return True
    if not download(PUNCT_FILE_URLS, PUNCT_DEST, min_bytes=PUNCT_MIN_BYTES):
        return False
    print("[punctuation] 就绪")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 voice2text 所需模型")
    parser.add_argument("--force", action="store_true", help="忽略已有文件强制重下")
    args = parser.parse_args()

    print(f"模型目录: {MODELS_DIR}")
    ok = install_asr(args.force)
    ok = install_punctuation(args.force) and ok
    ok = install_llm(args.force) and ok
    if not ok:
        print("模型下载未完成，请检查网络后重跑（已下载的部分会自动续传）")
        return 1
    print("全部模型就绪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
