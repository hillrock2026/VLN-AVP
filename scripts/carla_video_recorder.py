"""Minimal continuous frame recorder for the DEMO-01 car park run.

One real CARLA RGB onboard camera is attached to the ego for one execution
segment only (after Taichu has finished; no camera is active during the model
call).  It writes 1280x720 PNG frames with their real simulator frame ids and
timestamps.  The exact Taichu input remains the runner's per-round observation
PNG.  The recorder does not control the vehicle and does not generate frames.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import carla


class VideoRecorder:
    def __init__(
        self,
        session,
        ego,
        out_dir,
        *,
        width=640,
        height=360,
        fov=100.0,
        sensor_tick=0.1,
    ):
        self.session = session
        self.ego = ego
        self.out_dir = Path(out_dir)
        self.width = int(width)
        self.height = int(height)
        self.lock = threading.Lock()
        self.views = {}
        self.cameras = []
        self.out_dir.mkdir(parents=True, exist_ok=True)
        library = session.world.get_blueprint_library()
        # One onboard camera, active only during one execution segment. A
        # persistent camera during the Taichu pause overloaded the Epic
        # RenderThread (GameThread timed out waiting for RenderThread).
        specs = (
            ("onboard", "demo_video_onboard", (-4.0, 0.0, 2.0), (-5.0, 0.0), fov),
        )
        for name, role, offset, rotation, fov in specs:
            view_dir = self.out_dir / name
            view_dir.mkdir(parents=True, exist_ok=True)
            bp = library.find("sensor.camera.rgb")
            bp.set_attribute("image_size_x", str(self.width))
            bp.set_attribute("image_size_y", str(self.height))
            bp.set_attribute("fov", str(fov))
            bp.set_attribute("sensor_tick", str(sensor_tick))
            bp.set_attribute("role_name", role)
            transform = carla.Transform(
                carla.Location(x=offset[0], y=offset[1], z=offset[2]),
                carla.Rotation(pitch=rotation[0], yaw=rotation[1]),
            )
            camera = session.world.spawn_actor(bp, transform, attach_to=ego)
            session.actors.append(camera)
            view = {
                "name": name,
                "role": role,
                "fov": float(fov),
                "dir": str(view_dir),
                "transform": {
                    "x": offset[0],
                    "y": offset[1],
                    "z": offset[2],
                    "pitch": rotation[0],
                    "yaw": rotation[1],
                },
                "frames": [],
            }
            self.views[name] = view
            self.cameras.append(camera)
            camera.listen(self._callback(name, view_dir, view))
        self.metadata = {
            "width": self.width,
            "height": self.height,
            "views": {
                name: {key: value for key, value in view.items() if key != "frames"}
                for name, view in self.views.items()
            },
        }

    def _callback(self, name, view_dir, view):
        seen = set()

        def receive(image):
            frame = int(image.frame)
            if frame in seen:
                return
            seen.add(frame)
            path = view_dir / f"{name}_{frame:06d}.png"
            image.save_to_disk(str(path))
            entry = {
                "view": name,
                "frame": frame,
                "timestamp": round(float(image.timestamp), 6),
                "path": str(path),
            }
            with self.lock:
                view["frames"].append(entry)

        return receive

    def close(self):
        for camera in reversed(self.cameras):
            try:
                camera.stop()
                if camera.is_alive:
                    camera.destroy()
            except Exception:
                pass
            if camera in self.session.actors:
                self.session.actors.remove(camera)
        self.cameras = []
        metadata = dict(self.metadata)
        metadata["views"] = {
            name: {
                **{key: value for key, value in view.items() if key != "frames"},
                "frame_count": len(view["frames"]),
                "frames": view["frames"],
            }
            for name, view in self.views.items()
        }
        path = self.out_dir / "recorder.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=1, ensure_ascii=False)
        return {"dir": str(self.out_dir), "metadata": str(path), **metadata}
