"use client";

import { Rows3, Rows4 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useDensity, type Density } from "@/lib/density";
import { labels } from "@/lib/labels";

export function DensityToggle() {
  const [density, setDensity] = useDensity();
  const Icon = density === "comfortable" ? Rows3 : Rows4;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={labels.header.density}>
          <Icon aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>{labels.header.density}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={density}
          onValueChange={(value) => setDensity(value as Density)}
        >
          <DropdownMenuRadioItem value="compact">
            <Rows4 aria-hidden /> {labels.header.densityCompact}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="comfortable">
            <Rows3 aria-hidden /> {labels.header.densityComfortable}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
