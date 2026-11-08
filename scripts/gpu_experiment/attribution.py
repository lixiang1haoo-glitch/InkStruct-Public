"""Wall-clock attribution, unprofiled and local to the experiment process."""
import importlib
import time
from collections import defaultdict

class Attribution:
    def __init__(self):self.rows=defaultdict(lambda:{'calls':0,'seconds':0.});self.restore=[]
    def wrap(self,obj,name,label):
        old=getattr(obj,name)
        def measured(*args,**kwargs):
            start=time.perf_counter()
            try:return old(*args,**kwargs)
            finally:
                row=self.rows[label];row['calls']+=1;row['seconds']+=time.perf_counter()-start
        setattr(obj,name,measured);self.restore.append((obj,name,old))
    def generation(self):
        specs=[('inkstruct.profile','load_profile','profile_read_parse'),
               ('inkstruct.v62_exp','descriptors','semantic_descriptor_rebuild'),
               ('inkstruct.v61_author_strokes_batch','crossing_pairs','fallback_crossing'),
               ('inkstruct.v61_author_strokes_batch','contact_pairs','fallback_contact'),
               ('inkstruct.v61_candidate_expansion','fit_bounded_axes','component_axis_fit'),
               ('inkstruct.v61_candidate_expansion','fit_shared_similarity','component_isotropic_fit'),
               ('inkstruct.v61_candidate_expansion','correspondence','component_correspondence'),
               ('inkstruct.contextual_trajectory','anchors','anchors'),
               ('gzip','compress','output_compression'),('json','dumps','json_serialization')]
        for mod,name,label in specs:self.wrap(importlib.import_module(mod),name,label)
        from inkstruct.structures import StructureRepository
        self.wrap(StructureRepository,'get','structure_sql_read_decode')
        from inkstruct.v62_exp import SemanticCandidateGenerator,SemanticBatchStrokeFallback
        for name in ('prepare','expand','extend','inventory'):self.wrap(SemanticCandidateGenerator,name,'component_'+name)
        self.wrap(SemanticBatchStrokeFallback,'select','semantic_select_total')
        from pathlib import Path
        self.wrap(Path,'write_bytes','output_binary_write')
        return self
    def close(self):
        for obj,name,old in reversed(self.restore):setattr(obj,name,old)
        return dict(self.rows)
