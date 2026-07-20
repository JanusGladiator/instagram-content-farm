import time

import requests

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


class GraphAPIError(RuntimeError):
    pass


def create_image_container(ig_business_id: str, image_url: str, caption: str,
                            access_token: str, *, session=None) -> str:
    session = session or requests.Session()
    response = session.post(
        f"{GRAPH_API_BASE}/{ig_business_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": access_token},
        timeout=60,
    )
    body = response.json()
    if response.status_code != 200 or "id" not in body:
        raise GraphAPIError(f"image container creation failed: {body}")
    return body["id"]


def create_reel_container(ig_business_id: str, video_url: str, caption: str,
                           access_token: str, *, session=None) -> str:
    session = session or requests.Session()
    response = session.post(
        f"{GRAPH_API_BASE}/{ig_business_id}/media",
        data={
            "video_url": video_url,
            "caption": caption,
            "media_type": "REELS",
            "access_token": access_token,
        },
        timeout=60,
    )
    body = response.json()
    if response.status_code != 200 or "id" not in body:
        raise GraphAPIError(f"reel container creation failed: {body}")
    return body["id"]


def wait_for_container_ready(container_id: str, access_token: str, *, session=None,
                              max_attempts: int = 20, poll_seconds: float = 5.0) -> None:
    session = session or requests.Session()
    for _ in range(max_attempts):
        response = session.get(
            f"{GRAPH_API_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=30,
        )
        body = response.json()
        status = body.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise GraphAPIError(f"container {container_id} failed processing: {body}")
        time.sleep(poll_seconds)
    raise GraphAPIError(f"container {container_id} not ready after {max_attempts} polls")


def publish_container(ig_business_id: str, creation_id: str, access_token: str,
                       *, session=None) -> str:
    session = session or requests.Session()
    response = session.post(
        f"{GRAPH_API_BASE}/{ig_business_id}/media_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=60,
    )
    body = response.json()
    if response.status_code != 200 or "id" not in body:
        raise GraphAPIError(f"publish failed: {body}")
    return body["id"]


def verify_credentials(ig_business_id: str, access_token: str, *, session=None) -> dict:
    session = session or requests.Session()
    response = session.get(
        f"{GRAPH_API_BASE}/{ig_business_id}",
        params={"fields": "username", "access_token": access_token},
        timeout=30,
    )
    body = response.json()
    if response.status_code != 200 or "username" not in body:
        raise GraphAPIError(f"credential check failed: {body}")
    return body


if __name__ == "__main__":
    import os
    result = verify_credentials(os.environ["IG_BUSINESS_ID"], os.environ["IG_ACCESS_TOKEN"])
    print(f"OK - connected as @{result['username']}")
