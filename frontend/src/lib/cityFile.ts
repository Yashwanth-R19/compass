import type { CityFileRow, CityResponse } from "../api/types";

/** The one place `/city`'s columnar `rows` get turned into an object shape
 * -- shared by MapPage (subsystem graph + treemap), CodeCity, and anything
 * else that reads `/city`, so the column order (CITY_FILE_COLUMNS) is
 * decoded in exactly one place. */
export interface CityFile {
  path: string;
  subsystemId: number | null;
  loc: number;
  complexity: number;
  riskScore: number | null;
  riskConfidence: number | null;
  principalExpertId: number | null;
  lastModifiedAt: number;
  commitCount: number;
  isTest: boolean;
  churnWeighted: number;
}

export function toCityFile(row: CityFileRow): CityFile {
  const [
    path,
    subsystemId,
    loc,
    complexity,
    riskScore,
    riskConfidence,
    principalExpertId,
    lastModifiedAt,
    commitCount,
    isTest,
    churnWeighted,
  ] = row;
  return {
    path,
    subsystemId,
    loc,
    complexity,
    riskScore,
    riskConfidence,
    principalExpertId,
    lastModifiedAt,
    commitCount,
    isTest,
    churnWeighted,
  };
}

export function toCityFiles(city: CityResponse): CityFile[] {
  return city.files.rows.map(toCityFile);
}

export function citySubsystemLabelById(city: CityResponse): Map<number, string> {
  return new Map(city.subsystems.map((s) => [s.id, s.label]));
}

export function cityContributorNameById(city: CityResponse): Map<number, string> {
  return new Map(city.contributors.map((c) => [c.id, c.name]));
}
