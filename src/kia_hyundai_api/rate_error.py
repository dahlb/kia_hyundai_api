from aiohttp import ClientError


class RateError(ClientError):
    pass
