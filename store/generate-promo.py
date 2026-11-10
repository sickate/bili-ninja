"""Render a 24-bit Chrome Web Store promo tile (requires rsvg-convert and ImageMagick)."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "store" / "assets"
OUT.mkdir(parents=True, exist_ok=True)
svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="440" height="280" viewBox="0 0 440 280">
<rect width="440" height="280" fill="#202944"/>
<g fill="none" stroke="#8393B4" stroke-width="3" stroke-linecap="round">
<path d="M184 94H220Q236 94 236 110V126Q236 140 254 140H278"/>
<path d="M184 188H220Q236 188 236 172V154Q236 140 254 140"/>
</g>
<rect x="60" y="56" width="124" height="76" rx="17" fill="#FB5A8C"/>
<path d="M110 76L140 94L110 112Z" fill="white"/>
<rect x="60" y="152" width="124" height="72" rx="17" fill="#38466B"/>
<g fill="#FB5A8C">
<rect x="82" y="180" width="7" height="16" rx="3.5"/>
<rect x="96" y="170" width="7" height="36" rx="3.5"/>
<rect x="110" y="164" width="7" height="48" rx="3.5"/>
<rect x="124" y="174" width="7" height="28" rx="3.5"/>
<rect x="138" y="169" width="7" height="38" rx="3.5"/>
<rect x="152" y="180" width="7" height="16" rx="3.5"/>
</g>
<rect x="278" y="80" width="100" height="120" rx="21" fill="#F6F8FC"/>
<g fill="none" stroke="#A32756" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">
<path d="M328 109V150M312 136L328 152L344 136"/>
<path d="M309 169H347"/>
</g>
</svg>'''
output = OUT / "promo-440x280.png"
subprocess.run(["rsvg-convert", "--output", str(output)], input=svg.encode(), check=True)
subprocess.run(["magick", str(output), "-alpha", "off", "-strip", "-define", "png:color-type=2", str(output)], check=True)
print(f"Created {output.name}")
