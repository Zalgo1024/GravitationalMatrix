// F12 地理布局用：省级中心点（省会/首府近似坐标，WGS84）。
// 只用于把节点摆到「大致正确的省份位置」，不是测绘成果，也不用于任何量算。
// 码值与 backend/app/data/regions.json（GB/T 2260）保持一致。

export interface ProvinceCenter {
  code: string;
  name: string;
  lng: number;
  lat: number;
}

export const PROVINCE_CENTERS: ProvinceCenter[] = [
  { code: "110000", name: "北京市", lng: 116.41, lat: 39.9 },
  { code: "120000", name: "天津市", lng: 117.2, lat: 39.13 },
  { code: "130000", name: "河北省", lng: 114.51, lat: 38.04 },
  { code: "140000", name: "山西省", lng: 112.55, lat: 37.87 },
  { code: "150000", name: "内蒙古自治区", lng: 111.75, lat: 40.84 },
  { code: "210000", name: "辽宁省", lng: 123.43, lat: 41.8 },
  { code: "220000", name: "吉林省", lng: 125.32, lat: 43.82 },
  { code: "230000", name: "黑龙江省", lng: 126.53, lat: 45.8 },
  { code: "310000", name: "上海市", lng: 121.47, lat: 31.23 },
  { code: "320000", name: "江苏省", lng: 118.78, lat: 32.04 },
  { code: "330000", name: "浙江省", lng: 120.15, lat: 30.27 },
  { code: "340000", name: "安徽省", lng: 117.28, lat: 31.86 },
  { code: "350000", name: "福建省", lng: 119.3, lat: 26.08 },
  { code: "360000", name: "江西省", lng: 115.89, lat: 28.68 },
  { code: "370000", name: "山东省", lng: 117.0, lat: 36.65 },
  { code: "410000", name: "河南省", lng: 113.62, lat: 34.75 },
  { code: "420000", name: "湖北省", lng: 114.3, lat: 30.59 },
  { code: "430000", name: "湖南省", lng: 112.94, lat: 28.23 },
  { code: "440000", name: "广东省", lng: 113.26, lat: 23.13 },
  { code: "450000", name: "广西壮族自治区", lng: 108.32, lat: 22.82 },
  { code: "460000", name: "海南省", lng: 110.33, lat: 20.03 },
  { code: "500000", name: "重庆市", lng: 106.55, lat: 29.56 },
  { code: "510000", name: "四川省", lng: 104.07, lat: 30.67 },
  { code: "520000", name: "贵州省", lng: 106.63, lat: 26.65 },
  { code: "530000", name: "云南省", lng: 102.83, lat: 24.88 },
  { code: "540000", name: "西藏自治区", lng: 91.11, lat: 29.65 },
  { code: "610000", name: "陕西省", lng: 108.94, lat: 34.34 },
  { code: "620000", name: "甘肃省", lng: 103.83, lat: 36.06 },
  { code: "630000", name: "青海省", lng: 101.78, lat: 36.62 },
  { code: "640000", name: "宁夏回族自治区", lng: 106.27, lat: 38.47 },
  { code: "650000", name: "新疆维吾尔自治区", lng: 87.62, lat: 43.82 },
  { code: "710000", name: "台湾省", lng: 121.52, lat: 25.03 },
  { code: "810000", name: "香港特别行政区", lng: 114.17, lat: 22.32 },
  { code: "820000", name: "澳门特别行政区", lng: 113.55, lat: 22.2 },
];

const CENTER_BY_CODE = new Map(PROVINCE_CENTERS.map((item) => [item.code, item]));

export function provinceCenter(code?: string | null): ProvinceCenter | undefined {
  return code ? CENTER_BY_CODE.get(code) : undefined;
}

/** 节点省名的单字简称（用于属地徽标）；取不到时返回空串。 */
export function provinceBadge(name?: string | null): string {
  if (!name) return "";
  const trimmed = name.replace(/(省|市|自治区|特别行政区|壮族|回族|维吾尔|特区)$/g, "");
  return trimmed.slice(0, 1);
}
