"""Advanced B: Nav2 navigation instead of teleport (decision 015).

Pure-python modules (world / map / robot description generation, analysis) import on the
Mac; modules that need rclpy (``smoke``, ``b0_driver``) import it inside ``main`` and only
run in the ``inspection-ap-nav`` container.
"""
