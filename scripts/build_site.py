"""Build docs/index.html (the public site) from src/. Run from the project root: python3 scripts/build_site.py"""
import datetime, json, os
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = lambda p: open(os.path.join(root, 'src', p), encoding='utf-8').read()
body = (src('template.html')
        .replace('/*CORE*/', src('core.js'))
        .replace('/*DEMO*/', src('demo.json').replace('</', '<\\/')))
page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="description" content="Andhra Pradesh public money in plain words: state audit findings, every gram panchayat\'s grants and photo-proof works, and a monthly voucher checker.">\n'
        '<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}</style>\n'
        '</head>\n<body>\n' + body + '\n</body>\n</html>\n')
open(os.path.join(root, 'docs', 'index.html'), 'w', encoding='utf-8').write(page)
json.dump({'updated': datetime.date.today().strftime('%d %b %Y')}, open(os.path.join(root, 'docs', 'data', 'meta.json'), 'w'))
print('built docs/index.html', len(page), 'bytes')
