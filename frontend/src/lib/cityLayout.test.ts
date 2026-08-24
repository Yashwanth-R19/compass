import { describe, expect, it } from "vitest";
import { layoutCity, MAX_CITY_BUILDINGS, type CityLayoutInput } from "./cityLayout";

function overlaps(a: { x: number; z: number; width: number; depth: number }, b: typeof a): boolean {
  const EPS = 1e-6;
  return (
    a.x + a.width > b.x + EPS &&
    b.x + b.width > a.x + EPS &&
    a.z + a.depth > b.z + EPS &&
    b.z + b.depth > a.z + EPS
  );
}

function makeInput(filesPerDistrict: number, districtCount = 3): CityLayoutInput {
  const subsystems = Array.from({ length: districtCount }, (_, i) => ({
    id: i + 1,
    label: `district-${i}`,
    totalLoc: 0,
  }));
  const files = [];
  for (let d = 0; d < districtCount; d++) {
    for (let i = 0; i < filesPerDistrict; i++) {
      const loc = 10 + ((d * filesPerDistrict + i) % 200);
      files.push({
        path: `district-${d}/file_${i}.py`,
        subsystemId: d + 1,
        loc,
        complexity: 1 + (i % 20),
        churnWeighted: i % 50,
        commitCount: i % 10,
      });
      subsystems[d].totalLoc += loc;
    }
  }
  return { subsystems, files };
}

describe("layoutCity", () => {
  it("is deterministic -- the same input produces a deep-equal output across 10 calls", () => {
    const input = makeInput(30);
    const first = layoutCity(input, { width: 300, depth: 300 });
    for (let i = 0; i < 10; i++) {
      expect(layoutCity(input, { width: 300, depth: 300 })).toEqual(first);
    }
  });

  it("district areas are proportional to total LOC within tolerance", () => {
    const input = makeInput(30);
    const result = layoutCity(input, { width: 400, depth: 400, streetGap: 2 });
    const totalLoc = input.subsystems.reduce((s, d) => s + d.totalLoc, 0);
    const totalArea = result.districts.reduce((s, d) => s + d.width * d.depth, 0);
    for (const district of result.districts) {
      const expectedShare = district.totalLoc / totalLoc;
      const actualShare = (district.width * district.depth) / totalArea;
      expect(actualShare).toBeGreaterThan(expectedShare - 0.05);
      expect(actualShare).toBeLessThan(expectedShare + 0.05);
    }
  });

  it("no two buildings overlap, including outskirts plates", () => {
    const input = makeInput(40, 4);
    const result = layoutCity(input, { width: 500, depth: 500 });
    const all = [...result.buildings, ...result.outskirts];
    for (let i = 0; i < all.length; i++) {
      for (let j = i + 1; j < all.length; j++) {
        expect(overlaps(all[i], all[j])).toBe(false);
      }
    }
  });

  it("the MAX_CITY_BUILDINGS cap engages above the threshold and reports it honestly", () => {
    const smallInput = makeInput(10, 2);
    const smallResult = layoutCity(smallInput, { width: 300, depth: 300 });
    expect(smallResult.capped).toBe(false);
    expect(smallResult.outskirts).toEqual([]);
    expect(smallResult.buildingsShown).toBe(smallResult.totalFiles);

    const bigInput = makeInput(Math.ceil((MAX_CITY_BUILDINGS + 500) / 2), 2);
    const bigResult = layoutCity(bigInput, { width: 800, depth: 800 });
    expect(bigResult.totalFiles).toBeGreaterThan(MAX_CITY_BUILDINGS);
    expect(bigResult.capped).toBe(true);
    expect(bigResult.buildingsShown).toBe(MAX_CITY_BUILDINGS);
    expect(bigResult.outskirts.length).toBeGreaterThan(0);
  });

  it("gives every file with no subsystem a shared 'Unassigned' district rather than dropping it", () => {
    const input: CityLayoutInput = {
      subsystems: [{ id: 1, label: "known", totalLoc: 100 }],
      files: [
        {
          path: "known/a.py",
          subsystemId: 1,
          loc: 100,
          complexity: 1,
          churnWeighted: 0,
          commitCount: 1,
        },
        {
          path: "orphan.py",
          subsystemId: null,
          loc: 20,
          complexity: 1,
          churnWeighted: 0,
          commitCount: 1,
        },
      ],
    };
    const result = layoutCity(input, { width: 200, depth: 200 });
    expect(result.districts.map((d) => d.label).sort()).toEqual(["Unassigned", "known"]);
    expect(result.buildings.map((b) => b.path).sort()).toEqual(["known/a.py", "orphan.py"]);
  });

  it("height is normalized against the chosen metric and always within [minHeight, maxHeight]", () => {
    const input = makeInput(20);
    const result = layoutCity(input, {
      width: 300,
      depth: 300,
      heightMetric: "churn",
      minHeight: 1,
      maxHeight: 10,
    });
    for (const b of result.buildings) {
      expect(b.height).toBeGreaterThanOrEqual(1);
      expect(b.height).toBeLessThanOrEqual(10);
    }
  });
});
