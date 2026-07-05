/** Smoke tests for learner model store helpers. */

import { describe, it, expect } from "vitest"
import { getMasteryLabel, getStatusColor } from "../stores/skills-store"

describe("skills-store helpers", () => {
  it("getMasteryLabel returns correct labels", () => {
    expect(getMasteryLabel(0.96)).toBe("mastered")
    expect(getMasteryLabel(0.85)).toBe("proficient")
    expect(getMasteryLabel(0.65)).toBe("developing")
    expect(getMasteryLabel(0.30)).toBe("emerging")
    expect(getMasteryLabel(0)).toBe("not_seen")
  })

  it("getStatusColor returns valid CSS colors", () => {
    expect(getStatusColor(0.96)).toMatch(/^#[0-9a-f]{6}$/)
    expect(getStatusColor(0)).toMatch(/^#[0-9a-f]{6}$/)
  })
})
