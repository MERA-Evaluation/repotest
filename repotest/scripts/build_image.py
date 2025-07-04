"""
    Temp logic to build custom images

    This script is used to build a custom Docker image for a specific application.
    It takes the name of the image as an argument and builds the image using the Dockerfile
    in the corresponding folder.

"""
import docker
import logging
from pathlib import Path

logger = logging.getLogger("repotest")

def build_image(image_folder):
    # Initialize Docker client
    client = docker.from_env()

    # Define the path to the build context (folder containing Dockerfile)
    path = str(Path(__file__).parent / "images" / image_folder)
    print(path)
    # Define the image name

    print(f"image_folder = {image_folder} Building Docker image '{image_folder}' from '{path}'...")
    logger.info(f"image_folder = {image_folder} Building Docker image '{image_folder}' from '{path}'...")
    # Build the Docker image
    image, build_logs = client.images.build(path=path, tag=image_folder)

    # Print build logs
    for log in build_logs:
        if "stream" in log:
            logger.info(log["stream"].strip())

    print(f"Image '{image_folder}' built successfully!")

