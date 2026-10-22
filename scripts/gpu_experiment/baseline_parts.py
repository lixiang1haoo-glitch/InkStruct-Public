"""Unprofiled wall-time attribution of IO, parsing, math and page layout."""
import bootstrap as b
import json
import time
import zipfile
from pathlib import Path
from attribution import Attribution
from inkstruct.document import package,math_adapter
from inkstruct.editor import mixed
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.layout import inline
from inkstruct.renderers.pages import page_svg

rows=[]
for rep in range(3):
    a=Attribution()
    a.wrap(Path,'read_bytes','filesystem_read_bytes')
    a.wrap(zipfile.ZipFile,'read','zip_member_read_decompress')
    a.wrap(package,'read_json','package_json_parse')
    a.wrap(mixed,'parse_markdown','markdown_parse_including_math')
    a.wrap(mixed,'layout_markdown','layout_measure_paginate')
    a.wrap(inline,'measure_math','math_measure_geometry')
    if hasattr(math_adapter,'parse_math'):a.wrap(math_adapter,'parse_math','formula_parse')
    try:
        start=time.perf_counter();loaded=package.load_package(b.ROOT/'artifacts/preview_performance_0.1.12_20261018/input.inkdoc')
        load=time.perf_counter()-start;t=time.perf_counter()
        result=mixed.build_markdown(loaded.session,0,loaded.resolver,'','',loaded.page,loaded.style,loaded.flow,None,MarkdownBuildCache())
        build=time.perf_counter()-t;t=time.perf_counter()
        svg=page_svg(result['snapshot'],5,debug=True).encode();svg_build=time.perf_counter()-t
        t=time.perf_counter();output=b.OUT/'tmp/baseline.svg';output.write_bytes(svg);write=time.perf_counter()-t
    finally:parts=a.close()
    rows.append({'repeat':rep,'load_s':load,'build_s':build,'svg_build_s':svg_build,'svg_write_s':write,
                 'inclusive_parts_not_additive':parts})
b.save('baseline-parts.json',rows)
print(json.dumps(rows,indent=2),flush=True)
