"""Conservative same-length plain-paragraph edit experiment with full fallback.

Not a general incremental Markdown parser: never slices lists, formulas, tables,
fields, definitions, fences, HTML, notes or changes to block delimiters.
"""
from dataclasses import fields, is_dataclass, replace
import re
from inkstruct.document.editing import SourceSession
from inkstruct.document.schema import SourceSpan
from inkstruct.document.markdown import parse_markdown as full_parse

def rebase(value, offset):
    if isinstance(value, SourceSpan): return SourceSpan(value.start+offset,value.end+offset)
    if is_dataclass(value):return replace(value,**{f.name:rebase(getattr(value,f.name),offset) for f in fields(value) if f.init})
    if isinstance(value,tuple):return tuple(rebase(v,offset) for v in value)
    return value

class IncrementalParser:
    def __init__(self):self.previous=None;self.hits=0;self.fallbacks=0
    def __call__(self,session,*,dialect='markdown',cancelled=None,field_blocks=False):
        old=self.previous
        doc=None
        if (old and dialect=='markdown' and not field_blocks and
            old.document_id==session.document_id and len(old.source)==len(session.source) and
            not any(token in session.source for token in ('[^', '\\label','\\ref','\r',':::'))):
            changed=[i for i,(a,b) in enumerate(zip(old.source,session.source)) if a!=b]
            if len(changed)==1 and old.source[changed[0]].isdigit() and session.source[changed[0]].isdigit():
                pos=changed[0]
                candidates=[(i,n) for i,n in enumerate(old.nodes) if n.span.start<=pos<n.span.end]
                if len(candidates)==1:
                    index,node=candidates[0]
                    raw=session.source[node.span.start:node.span.end]
                    if node.kind=='paragraph' and re.fullmatch(r'[0-9A-Za-z\u4e00-\u9fff .,，。！？%+\-\n]+',raw):
                        local=SourceSession('',document_id=session.document_id)
                        local.source=raw;local.atom_ids=session.atom_ids[node.span.start:node.span.end]
                        local.revision=session.revision
                        part=full_parse(local,cancelled=cancelled)
                        if len(part.nodes)==1 and part.nodes[0].kind=='paragraph' and not part.diagnostics:
                            nodes=list(old.nodes);nodes[index]=rebase(part.nodes[0],node.span.start)
                            doc=replace(old,revision=session.revision,source=session.source,nodes=tuple(nodes))
        if doc is None:
            self.fallbacks+=1
            doc=full_parse(session,dialect=dialect,cancelled=cancelled,field_blocks=field_blocks)
        else:self.hits+=1
        self.previous=doc
        return doc
