import ctypes
import enum
import functools
import ipaddress
import typing

from . import constants
from .constants import AoEHeaderFlag

_commands = {}


def _use_for(key: str, command_id: constants.AdsCommandId, cls: type) -> type:
    if command_id not in _commands:
        _commands[command_id] = {}

    _commands[command_id][key] = cls
    cls._command_id = command_id
    return cls


def use_for_response(command_id: constants.AdsCommandId):
    """
    Decorator marking a class to be used for a specific AdsCommand response.
    """
    return functools.partial(_use_for, 'response', command_id)


def use_for_request(command_id: constants.AdsCommandId):
    """
    Decorator marking a class to be used for a specific AdsCommand request.
    """
    return functools.partial(_use_for, 'request', command_id)


def get_struct_by_command(command_id: constants.AdsCommandId, request: bool):
    key = 'request' if request else 'response'
    return _commands[command_id][key]


class _AdsStructBase(ctypes.LittleEndianStructure):
    # To be overridden by subclasses:
    _command_id: constants.AdsCommandId = constants.AdsCommandId.INVALID

    _pack_ = 1
    _dict_mapping = {}

    @property
    def _dict_attrs(self):
        for attr, *info in self._fields_:
            yield self._dict_mapping.get(attr, attr)

    def to_dict(self) -> dict:
        """Return the structure as a dictionary."""
        # Raw values can be retargeted to properties by way of _dict_mapping:
        #  {'raw_attr': 'property_attr'}
        return {attr: getattr(self, attr)
                for attr in self._dict_attrs}

    @property
    def serialized_length(self) -> int:
        return ctypes.sizeof(self)

    def __repr__(self):
        formatted_args = ", ".join(f"{k!s}={v!r}"
                                   for k, v in self.to_dict().items())
        return f"{self.__class__.__name__}({formatted_args})"


def _create_enum_property(field_name: str,
                          enum_cls: enum.Enum,
                          *,
                          doc: str = None,
                          strict: bool = True):
    """
    Create a property which makes a field value into an enum value.

    Parameters
    ----------
    field_name : str
        The field name (i.e., parameter 1 in the list of _fields_)

    enum_cls : enum.Enum
        The enum class.

    doc : str, optional
        Documentation for the property.

    strict : bool, optional
        Require values on get (and set) to be valid enum values.  If False, get
        may return raw values, and set may accept raw values (unknown or
        unacceptable enum values).
    """

    def fget(self):
        value = getattr(self, field_name)
        try:
            return enum_cls(value)
        except ValueError:
            if not strict:
                return value
            raise

    def fset(self, value):
        if strict:
            # Raises ValueError if invalid
            value = enum_cls(value).value

        setattr(self, field_name, value)

    return property(fget, fset, doc=doc)


def _create_byte_string_property(field_name: str, *, doc: str = None,
                                 encoding='utf-8'):
    """
    Create a property which makes handling byte string fields more convenient.

    Parameters
    ----------
    field_name : str
        The field name (i.e., parameter 1 in the list of _fields_)

    doc : str, optional
        Documentation for the property.

    encoding : str, optional
        Attempt to decode with this decoding on access (or encode when
        writing).
    """

    def fget(self) -> str:
        value = getattr(self, field_name)
        try:
            return value.decode(encoding)
        except ValueError:
            return value

    def fset(self, value: str):
        if isinstance(value, str):
            value = value.encode(encoding)
        setattr(self, field_name, value)

    return property(fget, fset, doc=doc)


class AmsNetId(_AdsStructBase):
    """
    The NetId of and ADS device can be represented in this structure.

    Net IDs are do not necessarily have to have a relation to an IP address,
    though by convention it may be wise to configure them similarly.
    """
    octets: ctypes.c_uint8 * 6

    _fields_ = [
        ('octets', ctypes.c_uint8 * 6),
    ]

    def __repr__(self):
        return '.'.join(str(c) for c in self.octets)

    @classmethod
    def from_ipv4(cls, ip: typing.Union[str, ipaddress.IPv4Address],
                  octet5: int = 1,
                  octet6: int = 1) -> 'AmsNetId':
        """
        Create an AMS Net ID based on an IPv4 address.

        Parameters
        ----------
        ip : ipaddress.IPv4Address or str
            The IP address to base the Net ID on.

        octet5 : int
            The 5th octet (i.e., 5 of 1.2.3.4.5.6).

        octet5 : int
            The 6th octet (i.e., 6 of 1.2.3.4.5.6).

        Returns
        -------
        net_id : AmsNetId
        """
        if not isinstance(ip, ipaddress.IPv4Address):
            ip = ipaddress.IPv4Address(ip)

        return cls(tuple(ip.packed) + (octet5, octet6))

    @classmethod
    def from_string(cls, addr: str) -> 'AmsNetId':
        """
        Create an AMS Net ID based on an AMS ID string.

        Parameters
        ----------
        addr : str
            The net ID string.

        Returns
        -------
        net_id : AmsNetId
        """
        try:
            parts = tuple(int(octet) for octet in addr.split('.'))
            if len(parts) != 6:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError(f'Not a valid AMS Net ID: {addr}')

        return cls(parts)


class AmsAddr(_AdsStructBase):
    """The full address of an ADS device can be stored in this structure."""
    net_id: AmsNetId
    _port: int

    _fields_ = [
        ('net_id', AmsNetId),

        # AMS Port number
        ('_port', ctypes.c_uint16),
    ]

    port = _create_enum_property('_port', constants.AmsPort, strict=False)
    _dict_mapping = {'_port': 'port'}

    def __repr__(self):
        port = self.port
        if hasattr(port, 'value'):
            return f'{self.net_id}:{self.port.value}({self.port.name})'
        return f'{self.net_id}:{self.port}'


class AdsVersion(_AdsStructBase):
    """Contains the version number, revision number and build number."""

    version: int
    revision: int
    build: int

    _fields_ = [
        ('version', ctypes.c_uint8),
        ('revision', ctypes.c_uint8),
        ('build', ctypes.c_uint16),
    ]


@use_for_response(constants.AdsCommandId.READ_DEVICE_INFO)
class AdsDeviceInfo(AdsVersion):
    """Contains the version number, revision number and build number."""
    _name: ctypes.c_char * 16
    name: str

    _fields_ = [
        # Inherits version information from AdsVersion
        ('_name', ctypes.c_char * 16),
    ]

    name = _create_byte_string_property('_name', encoding='utf-8')
    _dict_mapping = {'_name': 'name'}

    def __init__(self, version: int, revision: int, build: int, name: str):
        super().__init__()
        self.version = version
        self.revision = revision
        self.build = build
        self.name = name


class AdsNotificationAttrib(_AdsStructBase):
    """
    Contains all the attributes for the definition of a notification.

    The ADS DLL is buffered from the real time transmission by a FIFO.
    TwinCAT first writes every value that is to be transmitted by means
    of the callback function into the FIFO. If the buffer is full, or if
    the nMaxDelay time has elapsed, then the callback function is invoked
    for each entry. The nTransMode parameter affects this process as follows:

    ADSTRANS_SERVERCYCLE
    The value is written cyclically into the FIFO at intervals of
    nCycleTime. The smallest possible value for nCycleTime is the cycle
    time of the ADS server; for the PLC, this is the task cycle time.
    The cycle time can be handled in 1ms steps. If you enter a cycle time
    of 0 ms, then the value is written into the FIFO with every task cycle.

    ADSTRANS_SERVERONCHA
    A value is only written into the FIFO if it has changed. The real-time
    sampling is executed in the time given in nCycleTime. The cycle time
    can be handled in 1ms steps. If you enter 0 ms as the cycle time, the
    variable is written into the FIFO every time it changes.

    Warning: Too many read operations can load the system so heavily that
    the user interface becomes much slower.

    Tip: Set the cycle time to the most appropriate values, and always
    close connections when they are no longer required.
    """

    callback_length: int
    _transmission_mode: int
    max_delay: int
    cycle_time: int

    _fields_ = [
        # Length of the data that is to be passed to the callback function.
        ('callback_length', ctypes.c_uint32),

        #  AdsTransmissionMode.SERVERCYCLE: The notification's callback
        #  function is invoked cyclically.
        #  AdsTransmissionMode.SERVERONCHA: The notification's callback
        #  function is only invoked when the value changes.
        ('_transmission_mode', ctypes.c_uint32),

        # The notification's callback function is invoked at the latest when
        # this time has elapsed. The unit is 100 ns.
        ('max_delay', ctypes.c_uint32),

        # The ADS server checks whether the variable has changed after this
        # time interval. The unit is 100 ns.  This can be repurposed as
        # "change_filter" in certain scenarios.
        ('cycle_time', ctypes.c_uint32),
    ]

    transmission_mode = _create_enum_property(
        '_transmission_mode', constants.AdsTransmissionMode,
        doc='Transmission mode settings (see AdsTransmissionMode)',
    )

    _dict_mapping = {'_transmission_mode': 'transmission_mode'}


class AdsNotificationHeader(_AdsStructBase):
    """This structure is also passed to the callback function."""

    notification_handle: int
    timestamp: int
    sample_size: int

    _fields_ = [
        # Handle for the notification. Is specified when the notification is
        # defined.
        ('notification_handle', ctypes.c_uint32),

        # Contains a 64-bit value representing the number of 100-nanosecond
        # intervals since January 1, 1601 (UTC).
        ('timestamp', ctypes.c_uint64),

        # Number of bytes transferred.
        ('sample_size', ctypes.c_uint32),
    ]

# *
#  @brief Type definition of the callback function required by the
#  AdsSyncAddDeviceNotificationReqEx() function.
#   pAddr Structure with NetId and port number of the ADS server.
#   pNotification pointer to a AdsNotificationHeader structure
#   hUser custom handle pass to AdsSyncAddDeviceNotificationReqEx()
#  during registration
# /
# typedef void (* PAdsNotificationFuncEx)(const AmsAddr* pAddr, const
# AdsNotificationHeader* pNotification, ctypes.c_uint32 hUser);


class AdsSymbolEntry(_AdsStructBase):
    """
    This structure describes the header of ADS symbol information

    Calling AdsSyncReadWriteReqEx2 with IndexGroup == ADSIGRP_SYM_INFOBYNAMEEX
    will return ADS symbol information in the provided readData buffer.
    The header of that information is structured as AdsSymbolEntry and can
    be followed by zero terminated strings for "symbol name", "type name"
    and a "comment"
    """
    entry_length: int
    index_group: constants.AdsIndexGroup
    index_offset: int
    size: int
    _data_type: int
    _flags: int
    name_length: int
    type_length: int
    comment_length: int

    _fields_ = [
        # length of complete symbol entry
        ('entry_length', ctypes.c_uint32),
        # indexGroup of symbol: input, output etc.
        ('_index_group', ctypes.c_uint32),
        # indexOffset of symbol
        ('index_offset', ctypes.c_uint32),
        # size of symbol ( in bytes, 0 = bit )
        ('size', ctypes.c_uint32),
        # adsDataType of symbol
        ('_data_type', ctypes.c_uint32),
        # see ADSSYMBOLFLAG_*
        ('_flags', ctypes.c_uint32),
        # length of symbol name (null terminating character not counted)
        ('name_length', ctypes.c_uint16),
        # length of type name (null terminating character not counted)
        ('type_length', ctypes.c_uint16),
        # length of comment (null terminating character not counted)
        ('comment_length', ctypes.c_uint16),
    ]

    flags = _create_enum_property('_flags', constants.AdsSymbolFlag)
    data_type = _create_enum_property('_data_type', constants.AdsDataType)
    index_group = _create_enum_property('_index_group',
                                        constants.AdsIndexGroup)
    _dict_mapping = {'_flags': 'flags',
                     '_data_type': 'data_type',
                     '_index_group': 'index_group'
                     }


@use_for_request(constants.AdsCommandId.READ_WRITE)
class AdsReadWriteRequest(_AdsStructBase):
    """
    With ADS Read/Write `data` will be written to an ADS device. Data can also
    be read from the ADS device.

    SYM_HNDBYNAME = 0xF003
        The data which can be read are addressed by the Index Group and the
        Index Offset, or by way of symbol name (held in data).
    """
    index_group: constants.AdsIndexGroup
    index_offset: int
    read_length: int
    write_length: int
    _data_start: ctypes.c_ubyte * 0
    data: typing.Any = None

    _fields_ = [
        ('_index_group', ctypes.c_uint32),
        ('index_offset', ctypes.c_uint32),
        ('read_length', ctypes.c_uint32),
        ('write_length', ctypes.c_uint32),
        ('_data_start', ctypes.c_ubyte * 0),
    ]

    @classmethod
    def from_buffer_extended(cls, buf):
        struct = cls.from_buffer(buf)
        data_start = AdsReadWriteRequest._data_start.offset
        struct.data = bytearray(
            buf[data_start:data_start + struct.write_length])
        return struct

    index_group = _create_enum_property('_index_group',
                                        constants.AdsIndexGroup)
    _dict_mapping = {'_data_start': 'data',
                     '_index_group': 'index_group'}


class AdsSymbolInfoByName(_AdsStructBase):
    """Used to provide ADS symbol information for ADS SUM commands."""
    # indexGroup of symbol: input, output etc.
    index_group: constants.AdsIndexGroup
    index_offset: int
    length: int

    _fields_ = [
        ('_index_group', ctypes.c_uint32),
        # indexOffset of symbol
        ('index_offset', ctypes.c_uint32),
        # Length of the data
        ('length', ctypes.c_uint32),
    ]

    index_group = _create_enum_property('_index_group',
                                        constants.AdsIndexGroup)
    _dict_mapping = {'_index_group': 'index_group'}


class AmsTcpHeader(_AdsStructBase):
    reserved: int
    length: int

    _fields_ = [
        ('reserved', ctypes.c_uint16),
        ('length', ctypes.c_uint32),
    ]

    def __init__(self, length: int = 0):
        super().__init__(0, length)


class AoERequestHeader(_AdsStructBase):
    group: int
    offset: int
    length: int

    _fields_ = [
        ('group', ctypes.c_uint32),
        ('offset', ctypes.c_uint32),
        ('length', ctypes.c_uint32),
    ]

    @classmethod
    def from_sdo(cls,
                 sdo_index: int,
                 sdo_sub_index: int,
                 data_length: int) -> 'AoERequestHeader':
        """
        Create an AoERequestHeader given SDO settings.

        Parameters
        ----------
        sdo_index : int
        sdo_sub_index : int
        data_length : int

        Returns
        -------
        AoERequestHeader
        """
        return cls(constants.SDO_UPLOAD, (sdo_index) << 16 | sdo_sub_index,
                   data_length)


class AoEWriteRequestHeader(AoERequestHeader):
    write_length: int

    _fields_ = [
        # Inherits fields from AoERequestHeader.
        ('write_length', ctypes.c_uint32),
    ]


@use_for_response(constants.AdsCommandId.READ_STATE)
class AdsReadStateResponse(_AdsStructBase):
    ads_state: int
    dev_state: int

    _fields_ = [
        ('_ads_state', ctypes.c_uint16),
        ('dev_state', ctypes.c_uint16),
    ]

    ads_state = _create_enum_property('_ads_state', constants.AdsState)
    _dict_mapping = {'_ads_state': 'ads_state'}


class AdsWriteControlRequest(_AdsStructBase):
    ads_state: int
    dev_state: int
    length: int

    _fields_ = [
        ('ads_state', ctypes.c_uint16),
        ('dev_state', ctypes.c_uint16),
        ('length', ctypes.c_uint32),
    ]


class AdsAddDeviceNotificationRequest(_AdsStructBase):
    group: int
    offset: int
    length: int
    mode: int
    max_delay: int
    cycle_time: (ctypes.c_ubyte * 16)

    _fields_ = [
        ('group', ctypes.c_uint32),
        ('offset', ctypes.c_uint32),
        ('length', ctypes.c_uint32),
        ('mode', ctypes.c_uint32),
        ('max_delay', ctypes.c_uint32),
        ('cycle_time', ctypes.c_uint32),
        ('reserved', ctypes.c_ubyte * 16),
    ]


class AoEHeader(_AdsStructBase):
    target: AmsAddr
    source: AmsAddr
    command_id: constants.AdsCommandId
    state_flags: constants.AoEHeaderFlag
    length: int
    error_code: int
    invoke_id: int

    _fields_ = [
        ('target', AmsAddr),
        ('source', AmsAddr),
        ('_command_id', ctypes.c_uint16),
        ('_state_flags', ctypes.c_uint16),
        ('length', ctypes.c_uint32),
        ('error_code', ctypes.c_uint32),
        ('invoke_id', ctypes.c_uint32),
    ]

    @property
    def is_response(self) -> bool:
        return (AoEHeaderFlag.RESPONSE in self.state_flags)

    @property
    def is_request(self) -> bool:
        return not self.is_response

    @classmethod
    def create_request(
            cls,
            target: AmsAddr,
            source: AmsAddr,
            command_id: constants.AdsCommandId,
            length: int,
            invoke_id: int, *,
            state_flags: constants.AoEHeaderFlag = AoEHeaderFlag.ADS_COMMAND,
            error_code: int = 0,
            ) -> 'AoEHeader':
        """Create a request header."""
        return cls(target, source, command_id, state_flags, length, error_code,
                   invoke_id)

    @classmethod
    def create_response(
            cls,
            target: AmsAddr,
            source: AmsAddr,
            command_id: constants.AdsCommandId,
            length: int,
            invoke_id: int, *,
            state_flags: AoEHeaderFlag = (AoEHeaderFlag.ADS_COMMAND |
                                          AoEHeaderFlag.RESPONSE),
            error_code: int = 0,
            ) -> 'AoEHeader':
        """Create a response header."""
        return cls(target, source, command_id, state_flags, length, error_code,
                   invoke_id)

    command_id = _create_enum_property('_command_id', constants.AdsCommandId)
    state_flags = _create_enum_property(
        '_state_flags', constants.AoEHeaderFlag)
    _dict_mapping = {'_command_id': 'command_id',
                     '_state_flags': 'state_flags'}


class AoEResponseHeader(_AdsStructBase):
    _fields_ = [
        ('result', ctypes.c_uint32),
    ]


class AoEReadResponseHeader(AoEResponseHeader):
    _fields_ = [
        # Inherits 'result' from AoEResponseHeader.
        ('read_length', ctypes.c_uint32),
    ]
