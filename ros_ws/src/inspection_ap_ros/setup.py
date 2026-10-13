from glob import glob

from setuptools import setup

package_name = "inspection_ap_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="inspection-robot-active-perception",
    description="ROS 2 live integration of the active-perception inspection experiment",
    license="BSD-3-Clause",
    entry_points={"console_scripts": [f"inspector = {package_name}.inspector_node:main"]},
)
