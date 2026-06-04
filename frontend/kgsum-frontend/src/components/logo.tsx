'use client';

import Image from "next/image";
import {ReactNode} from "react";
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || '';

export function Logo(): ReactNode {

    return (
        <Image
            src={`${BASE_PATH}/logo.png`}
            className="hidden md:block"
            width={80}
            height={80}
            alt="KGSum Logo"
        />
    );
}
