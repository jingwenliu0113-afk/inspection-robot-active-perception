"""Observation sources (worlds).

* ``synthetic``: analytic occlusion model. Development and correctness tests only;
  never a source of reported results.
* Gazebo Harmonic (ROS 2 Jazzy): the formal platform, added in a later milestone.
"""

from .base import ObservationSource
from .synthetic import SyntheticParams, SyntheticWorld

__all__ = ["ObservationSource", "SyntheticParams", "SyntheticWorld"]
