"""Mede RAM, VRAM e a divisão CPU/GPU do Ollama enquanto a corrida decorre (RNF2).

    python medir_recursos.py                 um registo a cada 15 s, até Ctrl+C
    python medir_recursos.py --intervalo 30

Escreve recursos_AAAAMMDD-HHMM.csv nesta pasta e, ao parar, mostra o máximo por
modelo. Não interfere com a corrida: só lê.
"""
import argparse
import csv
import datetime as dt
import shutil
import subprocess
import time
from pathlib import Path


def correr(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001
        return ""


def ollama():
    """Modelos carregados, pela API do Ollama (a mesma que a corrida usa):
    nome, tamanho em GB e percentagem em GPU."""
    import json
    import os
    import urllib.request
    url = os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/ps"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            dados = json.load(r)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for m in dados.get("models", []):
        tam, vr = m.get("size") or 0, m.get("size_vram") or 0
        pct = round(100 * vr / tam) if tam else None
        out.append((m.get("name", "?"), tam / 2**30, pct, f"{pct}% GPU / {100 - pct}% CPU" if pct is not None else ""))
    return out


def vram():
    if not shutil.which("nvidia-smi"):
        return None, None, None
    s = correr(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits"]).strip().splitlines()
    if not s:
        return None, None, None
    u, t, g = [float(x) for x in s[0].split(",")]
    return u / 1024, t / 1024, g


def ram():
    try:
        import psutil
        v = psutil.virtual_memory()
        return (v.total - v.available) / 2**30, v.total / 2**30
    except ImportError:
        s = correr(["powershell", "-NoProfile", "-Command",
                    "$o=Get-CimInstance Win32_OperatingSystem; \"$($o.TotalVisibleMemorySize) $($o.FreePhysicalMemory)\""])
        try:
            tot, livre = [float(x) for x in s.split()]
            return (tot - livre) / 2**20, tot / 2**20
        except ValueError:
            return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intervalo", type=int, default=15)
    a = ap.parse_args()
    ficheiro = Path(__file__).parent / f"recursos_{dt.datetime.now():%Y%m%d-%H%M}.csv"
    print(f"a registar em {ficheiro.name} (Ctrl+C para parar)")
    maximos = {}
    with open(ficheiro, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["quando", "modelo", "ollama_gb", "pct_gpu", "processador", "ram_usada_gb",
                    "ram_total_gb", "vram_usada_gb", "vram_total_gb", "util_gpu_pct"])
        try:
            while True:
                ru, rt = ram()
                vu, vt, ug = vram()
                ms = ollama() or [("(nenhum)", None, None, "")]
                for nome, gb, pg, proc in ms:
                    w.writerow([f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}", nome, f"{gb:.2f}" if gb else "", pg, proc,
                                f"{ru:.1f}" if ru else "", f"{rt:.1f}" if rt else "",
                                f"{vu:.1f}" if vu is not None else "", f"{vt:.1f}" if vt else "", ug])
                    if nome != "(nenhum)":
                        m = maximos.setdefault(nome, {"ollama_gb": 0, "ram": 0, "vram": 0, "proc": proc})
                        m["ollama_gb"] = max(m["ollama_gb"], gb or 0)
                        m["ram"] = max(m["ram"], ru or 0)
                        m["vram"] = max(m["vram"], vu or 0)
                        m["proc"] = proc
                f.flush()
                print(f"{dt.datetime.now():%H:%M:%S}  " + " | ".join(f"{n} {g:.1f} GB {p}" if g else f"{n}" for n, g, _, p in ms)
                      + (f"  RAM {ru:.1f}/{rt:.0f} GB" if ru else "") + (f"  VRAM {vu:.1f}/{vt:.0f} GB" if vu is not None else ""))
                time.sleep(a.intervalo)
        except KeyboardInterrupt:
            pass
    print("\nmáximos por modelo:")
    for n, m in maximos.items():
        print(f"  {n:45s} modelo {m['ollama_gb']:.1f} GB · RAM do sistema {m['ram']:.1f} GB · VRAM {m['vram']:.1f} GB · {m['proc']}")


if __name__ == "__main__":
    main()
