"use client";

import { motion } from "framer-motion";
import { Children, isValidElement } from "react";

interface Props {
  children: React.ReactNode;
}

export function BentoGrid({ children }: Props) {
  const items = Children.toArray(children).filter(isValidElement);

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 auto-rows-auto">
      {items.map((child, i) => (
        <motion.div
          key={child.key || i}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.05, duration: 0.3 }}
        >
          {child}
        </motion.div>
      ))}
    </div>
  );
}
