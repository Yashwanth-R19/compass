import React from "react";

const dyn = (name: string) => import(`./${name}`);

import "./foo.js";
import "./bar";
import { x } from "@app/aliased";

export function useAll() {
  return [React, dyn, x];
}
