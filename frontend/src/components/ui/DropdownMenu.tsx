import { DropdownMenu as RadixDropdownMenu } from "radix-ui";
import type { ReactNode } from "react";

/** Thin Radix DropdownMenu wrapper styled like `Select`'s item list. */
export function DropdownMenu({
  trigger,
  items,
  align = "end",
}: {
  trigger: ReactNode;
  items: { label: string; onSelect: () => void; icon?: ReactNode }[];
  align?: "start" | "center" | "end";
}) {
  return (
    <RadixDropdownMenu.Root>
      <RadixDropdownMenu.Trigger asChild>{trigger}</RadixDropdownMenu.Trigger>
      <RadixDropdownMenu.Portal>
        <RadixDropdownMenu.Content
          align={align}
          sideOffset={6}
          className="z-50 min-w-40 rounded-sm border border-border bg-bg-elevated p-1 text-xs text-text shadow-md"
        >
          {items.map((item) => (
            <RadixDropdownMenu.Item
              key={item.label}
              onSelect={item.onSelect}
              className="flex cursor-pointer items-center gap-2 rounded-xs px-2 py-1.5 outline-none data-[highlighted]:bg-bg-inset"
            >
              {item.icon}
              {item.label}
            </RadixDropdownMenu.Item>
          ))}
        </RadixDropdownMenu.Content>
      </RadixDropdownMenu.Portal>
    </RadixDropdownMenu.Root>
  );
}
