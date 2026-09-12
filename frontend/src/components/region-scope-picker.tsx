"use client";

// F10 地域范围选择器：省 → 市级联多选，产出行政区划码值列表（region_scope）。
// 不选任何项 = 不限地域（后端 region_scope=null，行为与既有完全一致）。

import { ChevronDown, MapPin, X } from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { apiRequest } from "@/lib/api";

interface CityNode {
  code: string;
  name: string;
  aliases: string[];
}
interface ProvinceNode {
  code: string;
  name: string;
  aliases: string[];
  cities: CityNode[];
}
interface RegionsPayload {
  version: number;
  provinces: ProvinceNode[];
}

export function RegionScopePicker({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (codes: string[]) => void;
}) {
  const [provinces, setProvinces] = useState<ProvinceNode[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    apiRequest<RegionsPayload>("/api/regions")
      .then((body) => { if (!cancelled) setProvinces(body.provinces ?? []); })
      .catch(() => { if (!cancelled) setLoadFailed(true); });
    return () => { cancelled = true; };
  }, []);

  const nameOf = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of provinces ?? []) {
      map.set(p.code, p.name);
      for (const c of p.cities) map.set(c.code, c.name);
    }
    return map;
  }, [provinces]);

  function toggle(codes: string[]) {
    const set = new Set(selected);
    const allOn = codes.every((code) => set.has(code));
    for (const code of codes) {
      if (allOn) set.delete(code);
      else set.add(code);
    }
    onChange([...set]);
  }

  function remove(code: string) {
    onChange(selected.filter((item) => item !== code));
  }

  function toggleExpanded(code: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  return <div className="region-scope" aria-label="地域范围">
    <button
      className={selected.length ? "composer-tool composer-tool--active" : "composer-tool"}
      type="button"
      onClick={() => setOpen((current) => !current)}
      disabled={loadFailed}
      title={loadFailed ? "码表加载失败" : "地域范围"}
    >
      <MapPin size={17} />
      <span>地域{selected.length ? `·${selected.length}` : ""}</span>
      <ChevronDown size={13} className={open ? "region-scope__chevron region-scope__chevron--open" : "region-scope__chevron"} />
    </button>
    {selected.length > 0 && <div className="region-scope__chips">
      {selected.map((code) => <span key={code} className="region-scope__chip">
        {nameOf.get(code) ?? code}
        <button type="button" onClick={() => remove(code)} aria-label={`移除 ${nameOf.get(code) ?? code}`}><X size={12} /></button>
      </span>)}
      <button type="button" className="region-scope__clear" onClick={() => onChange([])}>清空</button>
    </div>}
    {open && provinces && <div className="region-scope__panel" role="group" aria-label="选择地域范围">
      <p className="region-scope__hint">不选任何地区 = 不限地域。选省 = 全省范围；展开可精确到市。</p>
      <div className="region-scope__list">
        {provinces.map((province) => {
          const provinceOn = selected.includes(province.code);
          const citiesOn = province.cities.filter((city) => selected.includes(city.code)).length;
          return <div key={province.code} className="region-scope__province">
            <div className="region-scope__row">
              <label className="region-scope__name">
                <input type="checkbox" checked={provinceOn} onChange={() => toggle([province.code])} />
                <span>{province.name}</span>
              </label>
              {province.cities.length > 0 && <button type="button" className="region-scope__expand" onClick={() => toggleExpanded(province.code)}>
                {expanded.has(province.code) ? "收起" : `${province.cities.length} 个市`}{citiesOn ? `·选${citiesOn}` : ""}
              </button>}
            </div>
            {expanded.has(province.code) && province.cities.length > 0 && <div className="region-scope__cities">
              {province.cities.map((city) => <label key={city.code} className="region-scope__city">
                <input type="checkbox" checked={selected.includes(city.code)} onChange={() => toggle([city.code])} />
                <span>{city.name}</span>
              </label>)}
            </div>}
          </div>;
        })}
      </div>
    </div>}
  </div>;
}
