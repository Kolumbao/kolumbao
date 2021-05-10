# -*- coding: utf-8 -*-
import aiohttp


async def download(url: str) -> bytes:
    """
    Download a file with `aiohttp`

    Parameters
    ----------
    url : str
        The URI of the file

    Returns
    -------
    bytes
        The file data
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=None) as r:
            result = b""
            while True:
                chunk = await r.content.read(16144)
                if not chunk:
                    break
                result += chunk
            return result
