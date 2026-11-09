"""Classify retryable transport faults independently of verifier scores."""


def retryable_exception(exception_type, message=''):
    name = (exception_type or '').rsplit('.',1)[-1]
    text = ' '.join(message.lower().split())
    if any(value in text for value in ('no space left','disk quota','insufficient_quota',
                                      'invalid api key','unauthorized','authentication','permission denied',
                                      'cleanup failed','unable to resume')):
        return False
    if name in {'APIConnectionError','APITimeoutError','Timeout','RateLimitError','InternalServerError',
                'ServiceUnavailableError','BadGatewayError','GatewayTimeoutError','ConnectionError',
                'ConnectionResetError','ConnectionRefusedError','ConnectError','ConnectTimeout','ReadTimeout',
                'RemoteProtocolError','ServerDisconnectedError','EnvironmentStartTimeoutError'}:
        return True
    if name=='APIStatusError':
        return any(code in text for code in ('408','429','500','502','503','504'))
    if name in {'RuntimeError','APIError','DockerException','HTTPError','TimeoutError'}:
        return any(value in text for value in ('connection reset','connection refused','connection aborted',
                                               'temporary failure in name resolution','i/o timeout',
                                               'tls handshake timeout','unexpected eof','502 bad gateway',
                                               '503 service unavailable','503 no healthy backends','504 gateway timeout'))
    return False


def retry_delay(config, retry_number):
    return min(config['max_delay_seconds'],config['delay_seconds']*2**min(retry_number-1,20))
