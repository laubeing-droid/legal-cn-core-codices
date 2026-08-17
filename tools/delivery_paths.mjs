import path from "node:path";

const FINAL_DIRECTORIES = {
  constitution: "01_宪法/01_现行宪法",
  constitutionAmendment: "01_宪法/02_宪法修正案",
  law: "02_法律/01_法律",
  lawInterpretation: "02_法律/02_法律解释",
  majorDecision: "02_法律/03_有关法律问题和重大问题的决定",
  lawChange: "02_法律/04_修改与废止决定",
  administrativeRegulation: "03_行政法规",
  supervisoryRegulation: "04_监察法规",
  localRegulation: "05_地方立法/01_地方性法规",
  autonomousRegulation: "05_地方立法/02_自治条例",
  separateRegulation: "05_地方立法/03_单行条例",
  sezRegulation: "05_地方立法/04_经济特区法规",
  pudongRegulation: "05_地方立法/05_浦东新区法规",
  hainanFtpRegulation: "05_地方立法/06_海南自由贸易港法规",
  ministryRule: "06_规章/01_部门规章",
  localGovernmentRule: "06_规章/02_地方政府规章",
  spcInterpretation: "07_司法解释【独立规范类型】/01_最高人民法院司法解释",
  sppInterpretation: "07_司法解释【独立规范类型】/02_最高人民检察院司法解释",
  jointInterpretation: "07_司法解释【独立规范类型】/03_两高联合司法解释",
  judicialInterpretationChange: "07_司法解释【独立规范类型】/04_修改与废止决定",
  npcNormative: "08_其他规范性文件【非立法】/01_人大规范性文件",
  stateCouncilNormative:
    "08_其他规范性文件【非立法】/02_行政规范性文件/01_国务院规范性文件",
  stateCouncilOfficeNormative:
    "08_其他规范性文件【非立法】/02_行政规范性文件/02_国务院办公厅规范性文件",
  ministryNormative:
    "08_其他规范性文件【非立法】/02_行政规范性文件/03_国务院部门规范性文件",
  localAdministrativeNormative:
    "08_其他规范性文件【非立法】/02_行政规范性文件/04_地方行政规范性文件",
  supervisoryNormative: "08_其他规范性文件【非立法】/03_监察规范性文件",
  courtNormative: "09_司法机关其他规范性文件【非司法解释】/01_人民法院司法规范性文件",
  procuratorateNormative:
    "09_司法机关其他规范性文件【非司法解释】/02_人民检察院规范性文件",
  courtMinutes: "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/01_法院会议纪要",
  trialGuidance: "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/02_审判业务指导文件",
  fadawangSelected: "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/03_法答网精选",
  spcQaCollections:
    "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/04_法院业务答疑/01_最高法法律问答批次汇编",
  otherCourtQa:
    "10_司法业务指导、会议纪要与公开答疑【非规范性法源】/04_法院业务答疑/02_其他法院公开答疑",
  mojDomestic: "80_司法部仲裁案例【参考性、非规范性法源】/01_国内仲裁案例",
  mojForeign: "80_司法部仲裁案例【参考性、非规范性法源】/02_涉外仲裁案例",
  mojSetAside: "80_司法部仲裁案例【参考性、非规范性法源】/03_撤销与不予执行仲裁裁决案例",
  spcGuiding: "81_最高人民法院公开案例【非规范性法源】/01_最高人民法院指导性案例",
  spcTypical: "81_最高人民法院公开案例【非规范性法源】/02_最高人民法院典型案例",
  spcGazette: "81_最高人民法院公开案例【非规范性法源】/03_最高人民法院公报裁判文书",
  spcDisputeResolution: "81_最高人民法院公开案例【非规范性法源】/04_多元解纷参考案例",
  sppGuiding: "82_最高人民检察院公开案例【非规范性法源】/01_最高人民检察院指导性案例",
  sppTypical: "82_最高人民检察院公开案例【非规范性法源】/02_最高人民检察院典型案例",
  peopleCourtDatabase: "89_人民法院案例库入库参考案例【本地人工更新】",
};

export const REQUIRED_FINAL_DIRECTORIES = [
  "00_法律检索导航与效力适用规则",
  ...new Set(
    Object.values(FINAL_DIRECTORIES).flatMap((directory) => {
      const parts = directory.split("/");
      return parts.map((_, index) => parts.slice(0, index + 1).join("/"));
    }),
  ),
].sort((a, b) => a.localeCompare(b, "zh-CN"));

function normalizedSourcePath(relativePath) {
  return String(relativePath ?? "").replaceAll("\\", "/");
}

export function sanitizeFilenamePart(value, fallback = "未命名") {
  const cleaned = String(value ?? "")
    .normalize("NFKC")
    .replace(/[<>:"/\\|?*\u0000-\u001F\u200b\u200c\u200d\ufeff\u00a0]/g, " ")
    .replace(/\s+/g, " ")
    .replace(/[. ]+$/g, "")
    .trim();
  return (cleaned || fallback).slice(0, 48);
}

export function readableMarkdownFilename({
  objectType,
  title,
  officialCaseId = "",
  publicationDate = "",
  effectLabel = "",
  wjbs = "",
}) {
  const safeTitle = sanitizeFilenamePart(title);
  const safeDate = /^\d{4}-\d{2}-\d{2}$/.test(publicationDate)
    ? publicationDate
    : "日期不详";
  if (objectType === "legal_document" && wjbs) {
    return `${safeTitle}_${safeDate}_${sanitizeFilenamePart(effectLabel, "效力待核")}_${wjbs}.md`;
  }
  if (objectType === "case") {
    return `${safeTitle}_${sanitizeFilenamePart(officialCaseId, "")}_${safeDate}.md`;
  }
  return `${safeTitle}_${safeDate}.md`;
}

function legalDirectory({ categoryCode = "", title = "", agencyName = "", relativePath = "" }) {
  const source = normalizedSourcePath(relativePath);
  const changeDecision = /修改|废止|失效|清理/.test(title);
  if (categoryCode === "0000") {
    return /修正案/.test(title)
      ? FINAL_DIRECTORIES.constitutionAmendment
      : FINAL_DIRECTORIES.constitution;
  }
  if (categoryCode === "0100") return changeDecision ? FINAL_DIRECTORIES.lawChange : FINAL_DIRECTORIES.law;
  if (categoryCode === "0200") return FINAL_DIRECTORIES.majorDecision;
  if (categoryCode === "0300") return FINAL_DIRECTORIES.lawInterpretation;
  if (categoryCode === "0400") return FINAL_DIRECTORIES.administrativeRegulation;
  if (categoryCode === "0600") return FINAL_DIRECTORIES.supervisoryRegulation;
  if (categoryCode === "0700") return FINAL_DIRECTORIES.localRegulation;
  if (categoryCode === "0800") {
    return /自治条例/.test(title)
      ? FINAL_DIRECTORIES.autonomousRegulation
      : FINAL_DIRECTORIES.separateRegulation;
  }
  if (categoryCode === "0901") return FINAL_DIRECTORIES.sezRegulation;
  if (categoryCode === "0902") return FINAL_DIRECTORIES.pudongRegulation;
  if (categoryCode === "0903") return FINAL_DIRECTORIES.hainanFtpRegulation;
  if (categoryCode === "1100") {
    if (changeDecision) return FINAL_DIRECTORIES.judicialInterpretationChange;
    if (/最高人民法院.*最高人民检察院|最高人民检察院.*最高人民法院|两高/.test(`${agencyName} ${title}`)) {
      return FINAL_DIRECTORIES.jointInterpretation;
    }
    return /检察/.test(agencyName)
      ? FINAL_DIRECTORIES.sppInterpretation
      : FINAL_DIRECTORIES.spcInterpretation;
  }
  if (categoryCode === "1300") return FINAL_DIRECTORIES.ministryRule;
  if (categoryCode === "1400") return FINAL_DIRECTORIES.localGovernmentRule;
  if (categoryCode === "1600") return FINAL_DIRECTORIES.npcNormative;
  if (categoryCode === "1700") {
    if (/国务院办公厅/.test(agencyName)) return FINAL_DIRECTORIES.stateCouncilOfficeNormative;
    if (/国务院$/.test(agencyName)) return FINAL_DIRECTORIES.stateCouncilNormative;
    if (/人民政府|政府办公厅|政府办公室/.test(agencyName)) {
      return FINAL_DIRECTORIES.localAdministrativeNormative;
    }
    return FINAL_DIRECTORIES.ministryNormative;
  }
  if (categoryCode === "1800") return FINAL_DIRECTORIES.supervisoryNormative;
  if (categoryCode === "1900") return FINAL_DIRECTORIES.courtNormative;
  if (categoryCode === "2000") return FINAL_DIRECTORIES.courtNormative;
  if (categoryCode === "2100") return FINAL_DIRECTORIES.procuratorateNormative;
  if (source.includes("/02_法院司法规范性文件/")) return FINAL_DIRECTORIES.courtNormative;
  if (source.includes("/02_检察规范性文件/")) return FINAL_DIRECTORIES.procuratorateNormative;
  return FINAL_DIRECTORIES.npcNormative;
}

export function targetDirectoryForSource({
  relativePath,
  objectType,
  title = "",
  categoryCode = "",
  agencyName = "",
}) {
  const source = normalizedSourcePath(relativePath);
  if (objectType === "legal_document") {
    return legalDirectory({ categoryCode, title, agencyName, relativePath: source });
  }
  if (source.startsWith("04_仲裁系统/01_司法部案例库仲裁案例/")) {
    if (/撤销|不予执行/.test(title)) return FINAL_DIRECTORIES.mojSetAside;
    if (/涉外|国际|境外|外国/.test(title)) return FINAL_DIRECTORIES.mojForeign;
    return FINAL_DIRECTORIES.mojDomestic;
  }
  if (source.startsWith("02_法院系统/06_最高人民法院指导性案例/")) return FINAL_DIRECTORIES.spcGuiding;
  if (source.startsWith("02_法院系统/07_人民法院案例库_入库参考案例/")) {
    return FINAL_DIRECTORIES.peopleCourtDatabase;
  }
  if (source.startsWith("02_法院系统/09_最高人民法院公报_裁判文书选登/")) {
    return FINAL_DIRECTORIES.spcGazette;
  }
  if (source.startsWith("02_法院系统/10_法院官方选编及官方新媒体案例/")) {
    return /多元解纷|调解|解纷/.test(title)
      ? FINAL_DIRECTORIES.spcDisputeResolution
      : FINAL_DIRECTORIES.spcTypical;
  }
  if (
    objectType === "case"
    && source.startsWith("02_法院系统/02_法院司法规范性文件/")
    && /典型案例/.test(title)
  ) return FINAL_DIRECTORIES.spcTypical;
  if (source.startsWith("03_检察院系统/04_最高人民检察院指导性案例/")) return FINAL_DIRECTORIES.sppGuiding;
  if (source.startsWith("03_检察院系统/05_检察机关典型案例/")) return FINAL_DIRECTORIES.sppTypical;
  if (source.startsWith("02_法院系统/03_法院会议纪要/")) return FINAL_DIRECTORIES.courtMinutes;
  if (source.startsWith("02_法院系统/04_审判业务指导文件/")) return FINAL_DIRECTORIES.trialGuidance;
  if (
    objectType === "practice_reference"
    && source.startsWith("02_法院系统/02_法院司法规范性文件/")
  ) return FINAL_DIRECTORIES.trialGuidance;
  if (source.startsWith("02_法院系统/05_法答网精选与法院业务答疑/01_法答网精选/")) {
    return FINAL_DIRECTORIES.fadawangSelected;
  }
  if (source.startsWith("02_法院系统/05_法答网精选与法院业务答疑/02_最高法法律问答批次汇编/")) {
    return FINAL_DIRECTORIES.spcQaCollections;
  }
  if (source.startsWith("02_法院系统/05_法答网精选与法院业务答疑/03_其他法院公开答疑/")) {
    return FINAL_DIRECTORIES.otherCourtQa;
  }
  return "";
}

export function finalRelativeMarkdownPath(metadata) {
  const directory = targetDirectoryForSource(metadata);
  if (!directory) return "";
  return path.posix.join(directory, readableMarkdownFilename(metadata));
}
