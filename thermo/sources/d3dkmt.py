"""GPU temperatures from the Windows display kernel (the same source Task Manager uses).

Works without admin rights. LibreHardwareMonitor has no temperature for the Radeon iGPU on
this laptop, so this fills the gap.
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes as w

from thermo.model import Reading

log = logging.getLogger(__name__)

KMTQAITYPE_ADAPTERREGISTRYINFO = 8
KMTQAITYPE_ADAPTERPERFDATA = 62


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", w.DWORD), ("HighPart", w.LONG)]


class _ADAPTERINFO(ctypes.Structure):
    _fields_ = [("hAdapter", w.UINT), ("AdapterLuid", _LUID), ("NumOfSources", w.ULONG),
                ("bPrecisePresentRegionsPreferred", w.BOOL)]


class _ENUMADAPTERS2(ctypes.Structure):
    _fields_ = [("NumAdapters", w.ULONG), ("pAdapters", ctypes.POINTER(_ADAPTERINFO))]


class _PERFDATA(ctypes.Structure):
    _fields_ = [("PhysicalAdapterIndex", ctypes.c_uint32), ("MemoryFrequency", ctypes.c_uint64),
                ("MaxMemoryFrequency", ctypes.c_uint64), ("MaxMemoryFrequencyOC", ctypes.c_uint64),
                ("MemoryBandwidth", ctypes.c_uint64), ("PCIEBandwidth", ctypes.c_uint64),
                ("FanRPM", ctypes.c_uint32), ("Power", ctypes.c_uint32), ("Temperature", ctypes.c_uint32),
                ("PowerStateOverride", ctypes.c_ubyte)]


class _QUERYADAPTERINFO(ctypes.Structure):
    _fields_ = [("hAdapter", w.UINT), ("Type", ctypes.c_int), ("pPrivateDriverData", ctypes.c_void_p),
                ("PrivateDriverDataSize", w.UINT)]


class _REGISTRYINFO(ctypes.Structure):
    _fields_ = [("AdapterString", w.WCHAR * 260), ("BiosString", w.WCHAR * 260),
                ("DacType", w.WCHAR * 260), ("ChipType", w.WCHAR * 260)]


class _CLOSEADAPTER(ctypes.Structure):
    _fields_ = [("hAdapter", w.UINT)]


class D3dkmtTemps:
    def __init__(self):
        self._gdi = ctypes.WinDLL("gdi32")
        self._adapters: list[tuple[int, str]] = []
        e = _ENUMADAPTERS2()
        if self._gdi.D3DKMTEnumAdapters2(ctypes.byref(e)) != 0 or not e.NumAdapters:
            return
        arr = (_ADAPTERINFO * e.NumAdapters)()
        e.pAdapters = arr
        if self._gdi.D3DKMTEnumAdapters2(ctypes.byref(e)) != 0:
            return
        for a in arr[: e.NumAdapters]:
            reg = _REGISTRYINFO()
            if self._query(a.hAdapter, KMTQAITYPE_ADAPTERREGISTRYINFO, reg) and reg.AdapterString:
                self._adapters.append((a.hAdapter, reg.AdapterString))
            else:
                self._gdi.D3DKMTCloseAdapter(ctypes.byref(_CLOSEADAPTER(a.hAdapter)))

    def _query(self, handle: int, kind: int, struct) -> bool:
        q = _QUERYADAPTERINFO(handle, kind, ctypes.cast(ctypes.byref(struct), ctypes.c_void_p), ctypes.sizeof(struct))
        return self._gdi.D3DKMTQueryAdapterInfo(ctypes.byref(q)) == 0

    def read(self) -> list[Reading]:
        out = []
        for i, (handle, name) in enumerate(self._adapters):
            pd = _PERFDATA()
            ok = self._query(handle, KMTQAITYPE_ADAPTERPERFDATA, pd)
            # Reported in tenths of a degree Celsius (546 -> 54.6 °C, matching Task Manager).
            temp = pd.Temperature / 10 if ok and pd.Temperature else None
            out.append(Reading(f"/d3dkmt/{i}/temperature", name, "GPU Temperature", "temperature", temp))
        return out

    def close(self) -> None:
        for handle, _ in self._adapters:
            self._gdi.D3DKMTCloseAdapter(ctypes.byref(_CLOSEADAPTER(handle)))
        self._adapters = []
