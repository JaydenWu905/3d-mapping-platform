#!/usr/bin/env python3
"""Run the installed MrHash entrypoint with direct reader/compute telemetry.

No log parsing and no numerical changes: successful compute() returns are the
fusion counter. The installed reader supplies matching/skipping observations.
"""
from __future__ import annotations
import argparse
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models.live_progress import ProgressReporter


def instrument(module, reporter):
    state = {"reader": None, "fused": 0}

    def counts():
        reader = state["reader"]
        if reader is None:
            return {}
        end = reader.end_frame if reader.end_frame >= 0 else reader.num_messages
        selected = max(0, min(reader.num_messages, end) - max(1, reader.start_frame) + 1)
        return dict(selected_frames=selected, visited_frames=getattr(reader,"selected_count",0),
                    matched_frames=getattr(reader,"matched_count",0),
                    skipped_frames=getattr(reader,"skip",0), fused_frames=state["fused"])

    def publish(phase="mapping", force=False):
        values = counts()
        reporter.emit(phase, state["fused"] if phase == "mapping" else 0,
                      values.get("selected_frames",0) if phase == "mapping" else 0,
                      scope="input" if phase == "mapping" else "none", unit="帧",
                      force=force, **values)

    original_reader, original_geo = module.Ros1Reader, module.GeoWrapper

    class Reader(original_reader):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            state["reader"] = self
            publish(force=True)

        def __iter__(self):
            super().__iter__()
            messages = self.msgs
            def monitored_messages():
                try:
                    for message in messages:
                        yield message
                        # A missing-pose skip can stay inside Reader.__next__ for
                        # many messages; observe its counters at each raw boundary.
                        publish()
                finally:
                    publish(force=True)
            self.msgs = monitored_messages()
            return self

        def __next__(self):
            try:
                return super().__next__()
            finally:
                # Also publishes final missing-pose skips when iteration stops.
                publish()

    class Geometry:
        def __init__(self,*args,**kwargs):
            self.target = original_geo(*args,**kwargs)

        def __getattr__(self,name):
            return getattr(self.target,name)

        def compute(self,*args,**kwargs):
            result = self.target.compute(*args,**kwargs)
            state["fused"] += 1
            publish()
            return result

        def streamAllOut(self,*args,**kwargs):
            publish("exporting_native",force=True)
            return self.target.streamAllOut(*args,**kwargs)

        def extractMesh(self,*args,**kwargs):
            publish("exporting_mesh",force=True)
            return self.target.extractMesh(*args,**kwargs)

        def serializeData(self,*args,**kwargs):
            publish("exporting_voxels",force=True)
            return self.target.serializeData(*args,**kwargs)

    module.Ros1Reader, module.GeoWrapper = Reader, Geometry
    return state


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runner',type=Path,required=True);parser.add_argument('config')
    args=parser.parse_args()
    sys.path.insert(0,str(args.runner.parent))
    spec=importlib.util.spec_from_file_location('platform_mrhash_entrypoint',args.runner)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    instrument(module,ProgressReporter())
    module.main(args.config)


if __name__ == '__main__': main()
