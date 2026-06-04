import {ReactNode} from "react";
import Link from "next/link";
import {
    NavigationMenu,
    NavigationMenuContent,
    NavigationMenuItem,
    NavigationMenuLink,
    NavigationMenuList,
    NavigationMenuTrigger
} from "@/components/ui/navigation-menu";
import {Avatar, AvatarFallback, AvatarImage} from "@/components/ui/avatar";
import {ModeToggle} from "@/components/theme-toggle";
import {Logo} from "@/components/logo";
import {BannerMenu} from "@/components/banner-menu";


// Consistent styling for all main navigation links
const menuLinkClass = "font-normal px-3 py-2 transition-colors hover:bg-accent rounded-md";

// This class provides the necessary styling (padding, hover, block display)
const menuLinkBoldClass = "font-bold p-2 transition-colors hover:bg-accent rounded-md block";

export const NavBar = (): ReactNode => {
    return (
        <nav className="pt-4 pb-2 px-2 border-b-2 border-dotted flex items-center">
            {/* Standard Link usage for Logo */}
            <Link href="/">
                <Logo/>
            </Link>

            <NavigationMenu>
                <NavigationMenuList>
                    {/* Standard Links (Home & Statistics) still use asChild as intended */}
                    <NavigationMenuItem>
                        <NavigationMenuLink asChild>
                            <Link href="/" className={menuLinkClass}>Home</Link>
                        </NavigationMenuLink>
                    </NavigationMenuItem>

                    <NavigationMenuItem>
                        <NavigationMenuTrigger className={menuLinkClass}>
                            Try KGSum
                        </NavigationMenuTrigger>

                        <NavigationMenuContent className="font-normal p-2 min-w-[30vw]">
                            <div className="flex flex-row">
                                <div className="basis-1/4 relative min-h-[200px]">
                                   <BannerMenu/>
                                </div>

                                <div className="basis-3/4 pl-2">
                                    {/* FIX A: Wrapped Link in a plain DIV, removing NavigationMenuLink */}
                                    <div>
                                        <Link href="/explore" className={menuLinkBoldClass}>
                                            Explore Profiles
                                            <p className="text-muted-foreground text-sm font-normal">
                                                Browse available Knowledge Graphs and discover their metadata.
                                            </p>
                                        </Link>
                                    </div>

                                    {/* FIX B: Wrapped Link in a plain DIV */}
                                    <div>
                                        <Link href="/profile" className={menuLinkBoldClass}>
                                            Profile Online
                                            <p className="text-muted-foreground text-sm font-normal">
                                                Access the Knowledge Graph profiling service in real-time.
                                            </p>
                                        </Link>
                                    </div>

                                    {/* FIX C: Wrapped Link in a plain DIV */}
                                    <div>
                                        <Link href="/documentation/latest" className={menuLinkBoldClass}>
                                            API Documentation
                                            <p className="text-muted-foreground text-sm font-normal">
                                                Consult guides and examples to integrate our profiling APIs.
                                            </p>
                                        </Link>
                                    </div>
                                </div>
                            </div>
                        </NavigationMenuContent>
                    </NavigationMenuItem>

                    <NavigationMenuItem>
                        <NavigationMenuLink asChild>
                            <Link href="/statistics" className={menuLinkClass}>Statistics</Link>
                        </NavigationMenuLink>
                    </NavigationMenuItem>
                </NavigationMenuList>
            </NavigationMenu>

            <ModeToggle/>

            {/* FIX D: Link wraps the Avatar component to resolve the other nested <a> error */}
            <Link
                aria-label="https://github.com/isislab-unisa/KGSum"
                href={"https://github.com/isislab-unisa/KGSum"}
                target="_blank" // External link best practice
                rel="noopener noreferrer" // Security best practice
                className="ml-3 mr-3 block" // Move margin styles to the Link
            >
                <Avatar aria-label="GitHub KGSum">
                    <AvatarImage src="https://github.githubassets.com/assets/GitHub-Mark-ea2971cee799.png"/>
                    <AvatarFallback>GH</AvatarFallback>
                </Avatar>
            </Link>
        </nav>
    );
};
