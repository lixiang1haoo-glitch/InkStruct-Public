"""Lossless binary64 point sequence for private cross-process display snapshots."""
from array import array
from dataclasses import replace

class PackedPoints:
    def __init__(self,points):self.data=array('d',(v for point in points for v in point))
    def __len__(self):return len(self.data)//2
    def __iter__(self):
        for i in range(0,len(self.data),2):yield self.data[i],self.data[i+1]
    def __getitem__(self,index):
        if isinstance(index,slice):return tuple(self)[index]
        if index<0:index+=len(self)
        if not 0<=index<len(self):raise IndexError(index)
        return self.data[index*2],self.data[index*2+1]
    def __eq__(self,other):return tuple(self)==tuple(other)
    def __hash__(self):return hash(tuple(self))

def pack_snapshot(snapshot):
    return replace(snapshot,pages=tuple(replace(page,
        paint_ops=tuple(replace(op,points=PackedPoints(op.points)) for op in page.paint_ops),
        preview_ops=tuple(replace(op,points=PackedPoints(op.points)) for op in page.preview_ops))
        for page in snapshot.pages))
