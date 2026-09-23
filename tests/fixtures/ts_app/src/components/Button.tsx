import React from "react";

type ButtonProps = { label: string; onClick?: () => void };

/** Primary action button. */
export function Button({ label, onClick }: ButtonProps) {
  return <button onClick={onClick}>{label}</button>;
}

export const IconButton = ({ label }: ButtonProps) => <button aria-label={label}>*</button>;
