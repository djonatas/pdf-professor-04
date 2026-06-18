#!/usr/bin/env python3
"""
Gera slides hibrido (Gemini background + overlay) para uma lista de aulas.
Uso: python3 _rodar-hibrido.py batch_N.txt
"""
import sys, os, subprocess, time, random

list_file = sys.argv[1]
with open(list_file) as f:
    codes = [line.strip() for line in f if line.strip()]

total = len(codes)
print(f"📦 Processando {total} aulas do lote {list_file}")

ok = 0
fail = 0
for i, code in enumerate(codes):
    print(f"  [{i+1}/{total}] {code}...", end=" ", flush=True)
    try:
        result = subprocess.run(
            ['python3', '_gerar-slides-hibrido.py', code],
            capture_output=True, text=True, timeout=900, cwd='/root/repos/pdf-professor'
        )
        if result.returncode == 0:
            ok += 1
            # Get last line which usually has success msg
            last = [l for l in result.stdout.split('\n') if l.strip()][-1][:60]
            print(f"✅ ({last})")
        else:
            fail += 1
            err = result.stderr[:500] if result.stderr else result.stdout[-200:]
            print(f"❌ {err}")
            with open('/tmp/hibrido_erros.log', 'a') as f:
                f.write(f"{code}: {err}\n")
    except subprocess.TimeoutExpired:
        fail += 1
        print(f"⏰ timeout")
        with open('/tmp/hibrido_erros.log', 'a') as f:
            f.write(f"{code}: timeout\n")
    except Exception as e:
        fail += 1
        print(f"❌ {e}")
        with open('/tmp/hibrido_erros.log', 'a') as f:
            f.write(f"{code}: {e}\n")
    
    # Small delay between aulas
    if i < total - 1:
        time.sleep(random.uniform(1, 3))

print(f"\n📊 Lote {list_file}: {ok} ok, {fail} falhas")

if fail > 0:
    print(f"❌ Falhas salvas em /tmp/hibrido_erros.log")