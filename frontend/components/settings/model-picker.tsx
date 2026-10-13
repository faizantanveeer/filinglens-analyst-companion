"use client";

import { Check, ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import type { ModelOption } from "@/lib/settings";

/**
 * A model name field: type any name, or pick from the suggested models and (once loaded) the models
 * this key can actually use.
 */
export function ModelPicker({
  id,
  value,
  onChange,
  suggested,
  available = [],
  placeholder,
  describedBy,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  suggested: ModelOption[];
  available?: string[];
  placeholder?: string;
  describedBy?: string;
}) {
  const known = new Set(suggested.map((m) => m.id));
  const more = available.filter((m) => !known.has(m));
  const item = (model: string, note?: string) => (
    <DropdownMenuItem key={model} onSelect={() => onChange(model)} className="flex items-start gap-2">
      <Check className={value === model ? "mt-0.5 size-4 text-primary" : "mt-0.5 size-4 opacity-0"} aria-hidden />
      <span className="flex min-w-0 flex-col">
        <span className="truncate font-mono text-xs">{model}</span>
        {note && <span className="text-xs text-muted-foreground">{note}</span>}
      </span>
    </DropdownMenuItem>
  );

  return (
    <div className="flex gap-2">
      <Input
        id={id}
        value={value}
        placeholder={placeholder}
        spellCheck={false}
        autoComplete="off"
        aria-describedby={describedBy}
        onChange={(e) => onChange(e.target.value)}
      />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="outline" size="icon" aria-label="Choose a model">
            <ChevronDown aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="max-h-80 w-72 overflow-y-auto">
          {suggested.length > 0 && <DropdownMenuLabel>Suggested</DropdownMenuLabel>}
          {suggested.map((m) => item(m.id, m.note))}
          {more.length > 0 && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuLabel>Also available to your key</DropdownMenuLabel>
              {more.map((m) => item(m))}
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
