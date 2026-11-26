from collections import namedtuple
from contextvars import ContextVar
from inspect import iscoroutine
from time import monotonic
from typing import Any

import grpc
import xtlsapi

from node_client.config import env

_deadline: ContextVar[float | None] = ContextVar("core_api_deadline", default=None)


class _CallDetails(
    namedtuple("_CallDetails", "method timeout metadata credentials wait_for_ready compression"),
    grpc.ClientCallDetails,
):
    pass


class _CoreDeadlineInterceptor(grpc.UnaryUnaryClientInterceptor):
    def intercept_unary_unary(self, continuation, client_call_details, request):  # noqa: V105 — callback gRPC
        deadline = _deadline.get()
        if deadline is None:
            return continuation(client_call_details, request)

        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Истёк общий дедлайн gRPC-вызовов ядра")

        timeout = client_call_details.timeout
        return continuation(
            _CallDetails(
                client_call_details.method,
                remaining if timeout is None else min(timeout, remaining),
                client_call_details.metadata,
                client_call_details.credentials,
                client_call_details.wait_for_ready,
                client_call_details.compression,
            ),
            request,
        )


def _create_client(client_class, host, port):
    client = client_class(host, port)
    channel = getattr(client, "_channel", None)
    if isinstance(channel, grpc.Channel):
        # В xtlsapi 3.3 методы не принимают timeout. Пересоздаём stub-объекты
        # через тот же инициализатор xtlsapi, используя канал с перехватчиком.
        client._channel = grpc.intercept_channel(channel, _CoreDeadlineInterceptor())
        super(client_class, client).__init__()
    return client


class _TemplateXtlsApi:
    def XrayClient(self, host, port):
        return _create_client(xtlsapi.XrayClient, host, port)

    def SingboxClient(self, host, port):
        return _create_client(xtlsapi.SingboxClient, host, port)

    def __getattr__(self, name):
        return getattr(xtlsapi, name)


template_xtlsapi = _TemplateXtlsApi()


def template_module(module):
    return template_xtlsapi if module is xtlsapi else module


async def call_core_api(script, *args) -> Any:
    token = _deadline.set(monotonic() + env.command_timeout)
    try:
        result = script(*args)
        if iscoroutine(result):
            return await result
        return result
    finally:
        _deadline.reset(token)
