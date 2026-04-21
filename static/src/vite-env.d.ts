/// <reference types="vite/client" />
/// <reference types="react" />
/// <reference types="react-dom" />

import type { ReactElement } from "react";

declare global {
  namespace JSX {
    type Element = ReactElement;
  }
}

export {};
