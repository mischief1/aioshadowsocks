import re
import logging
import socket
import struct
from functools import lru_cache

import dns.resolver

from shadowsocks import protocol_flag as flag

STREAM_HOST_PATTERN = re.compile(".*(netflix|nflx|hulu|hbo).*")
resolver = dns.resolver.Resolver()


def is_stream_domain(domain):
    # 目前只匹配 netflix、hulu、HBO
    if STREAM_HOST_PATTERN.search(domain):
        return True
    return False


def logging_cahce_info():
    def wrapper(func):
        def decorated(*args, **kwargs):
            logging.debug(f"domain:{args[0]} cache_info: {func.cache_info()}")
            return func(*args, **kwargs)

        return decorated

    return wrapper


@logging_cahce_info()
@lru_cache(2 ** 8)
def get_ip_from_domain(domain):
    from shadowsocks import current_app

    if current_app.stream_dns_server and is_stream_domain(domain):
        # use dnspython to query extra dns nameservers
        resolver.nameservers = [current_app.stream_dns_server]
        try:
            res = resolver.query(domain, "A")
            logging.info(f"hit stream DNS: {domain} res: {res[0].to_text()}")
            return res[0].to_text()
        except Exception:
            logging.warning(
                f"Failed to query DNS: {domain} now dns server:{resolver.nameservers}"
            )
            return domain
    try:
        return socket.gethostbyname(domain.encode())
    except Exception:
        logging.warning(f"Failed to query DNS: {domain}")
        return domain


def parse_header(data):
    # shadowsocks protocol https://shadowsocks.org/en/spec/Protocol.html
    atype, dst_addr, dst_port, header_length = data[0], None, None, 0
    if atype == flag.ATYPE_IPV4:
        if len(data) >= 7:
            dst_addr = socket.inet_ntop(socket.AF_INET, data[1:5])
            dst_port = struct.unpack("!H", data[5:7])[0]
            header_length = 7
        else:
            logging.warning("header is too short")
    elif atype == flag.ATYPE_IPV6:
        if len(data) >= 19:
            dst_addr = socket.inet_ntop(socket.AF_INET6, data[1:17])
            dst_port = struct.unpack("!H", data[17:19])[0]
            header_length = 19
        else:
            logging.warning("header is too short")
    elif atype == flag.ATYPE_DOMAINNAME:
        if len(data) > 2:
            addrlen = data[1]
            if len(data) >= 4 + addrlen:
                dst_addr = data[2 : 2 + addrlen]
                dst_addr = get_ip_from_domain(dst_addr.decode())
                dst_port = struct.unpack("!H", data[2 + addrlen : addrlen + 4])[0]
                header_length = 4 + addrlen
            else:
                logging.warning("header is too short")
        else:
            logging.warning("header is too short")
    else:
        logging.warning(f"unknown atype: {atype}")

    return atype, dst_addr, dst_port, header_length
