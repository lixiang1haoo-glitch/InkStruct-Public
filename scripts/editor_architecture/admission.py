"""Avoid constructing cache entries proven larger than their existing budget.

No capacity increase or relaxed equality. Scope: unchanged embedded immutable
resource catalog in this experiment. Normal keys and checks remain for entries
that fit. A production version needs this catalog accounting on every pool epoch.
"""
from inkstruct.editor import mixed
from inkstruct.editor.build_cache import MarkdownBuildCache

class NoStore:
    def __init__(self):self.misses=self.skipped=0
    def get(self,key):self.misses+=1;return None
    def put(self,keys,value,weight):self.skipped+=1
    def statistics(self):return {'hits':0,'misses':self.misses,'skipped':self.skipped,'entries':0}

def catalog_weight(resolver):
    return sum(len(g.original_json)+512+sum(map(len,g.strokes))*128
               for pool in resolver.pools.values() for g in pool)

def configure(cache,resolver,*,layout=True,continuation=True):
    weight=catalog_weight(resolver)
    # The full-layout key retains the entire catalog, so it cannot be admitted
    # if the catalog alone exceeds the unchanged full-layout budget.
    if layout and weight>cache.layouts.max_weight:cache.layouts=NoStore()
    # Continuation's own deep graph accounting differs; require an observed
    # rejected entry of this exact catalog, rather than assuming this bound.
    if continuation and cache.continuation.statistics()['skipped']:
        cache.continuation.enabled=False
    return weight

def install_weight_shortcut(resolver,budget=192*1024**2):
    old=mixed.snapshot_weight
    objects=tuple(g for pool in resolver.pools.values() for g in pool)
    weight=catalog_weight(resolver)
    def snapshot_weight(snapshot,session,current):
        now=tuple(g for pool in current.pools.values() for g in pool)
        if weight>budget and len(now)==len(objects) and all(a is c for a,c in zip(objects,now)):
            return weight
        return old(snapshot,session,current)
    mixed.snapshot_weight=snapshot_weight
    return old
