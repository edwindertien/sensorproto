$fn = 40;
//centerhelp();
//holder();
//cover();
bottom();
module cover(){
difference(){
    hull(){
    translate([-8,-8,0])cylinder(d=7,h=7);
    translate([8,-8,0])cylinder(d=7,h=7);
    translate([8,8,0])cylinder(d=7,h=7);
    translate([-8,8,0])cylinder(d=7,h=7);
    }
    translate([-8,-8,0])cylinder(d=3.2,h=8);
    translate([8,-8,0])cylinder(d=3.2,h=8);
    translate([8,8,0])cylinder(d=3.2,h=8);
    translate([-8,8,0])cylinder(d=3.2,h=8);
    translate([0,-5,0])cube([20,10,5]);
    
                translate([-8,-8,6])cylinder(d=5,h=5);
    translate([8,-8,6])cylinder(d=5,h=5);
    translate([8,8,6])cylinder(d=5,h=5);
    translate([-8,8,6])cylinder(d=5,h=5);
    
    
    hull(){
            translate([-8,-8,0])cylinder(d=3.2,h=5);
    translate([8,-8,0])cylinder(d=3.2,h=5);
    translate([8,8,0])cylinder(d=3.2,h=5);
    translate([-8,8,0])cylinder(d=3.2,h=5);
    }
    }}

//bottom();
module centerhelp(){difference(){
    cylinder(d=9,h=4);
    translate([0,0,3.5])cylinder(d=4,h=5);
}}

module bottom() {difference(){
union(){
    hull(){cylinder(d=28,h=3);
    translate([14,-6,0])cube([21,12,5]);
    translate([35,0,0])cylinder(d=12,h=5);
        }
    hull(){
    translate([-8,-8,0])cylinder(d=7,h=3);
    translate([8,-8,0])cylinder(d=7,h=3);
    translate([8,8,0])cylinder(d=7,h=3);
    translate([-8,8,0])cylinder(d=7,h=3);
    }
        translate([-8,-8,1])cylinder(d=5.5,h=3.7);
    translate([8,-8,1])cylinder(d=5.5,h=3.7);
    translate([8,8,1])cylinder(d=5.5,h=3.7);
    translate([-8,8,1])cylinder(d=5.5,h=3.7);

}
translate([35,0,0])cylinder(d=5,h=8);
translate([35-8,0,0])cylinder(d=5,h=8);
translate([35-16,0,0])cylinder(d=5,h=8);
translate([35,0,4.2])cylinder(d=6,h=8);
translate([35-8,0,4.2])cylinder(d=6,h=8);
translate([35-16,0,4.2])cylinder(d=6,h=8);
translate([35,0,0])cylinder(d=6,h=0.8);
translate([35-8,0,0])cylinder(d=6,h=0.8);
translate([35-16,0,0])cylinder(d=6,h=0.8);

    cylinder(d=8,h=5);
 rotate([0,0,45])for(i=[0:90:360]){
    rotate([0,0,i]){translate([6,0,0])cylinder(d=2.5,h=5);translate([6,0,1.5])cylinder(d=5,h=5);}
}
    translate([-8,-8,0])cylinder(d=2.7,h=5);
    translate([8,-8,0])cylinder(d=2.7,h=5);
    translate([8,8,0])cylinder(d=2.7,h=5);
    translate([-8,8,0])cylinder(d=2.7,h=5);
}
}





module holder() {difference(){
union(){
    hull(){cylinder(d=28,h=3);
    translate([14,-6,0])cube([21,12,5]);
    translate([35,0,0])cylinder(d=12,h=5);}
}
translate([35,0,0])cylinder(d=5,h=8);
translate([35-8,0,0])cylinder(d=5,h=8);
translate([35-16,0,0])cylinder(d=5,h=8);
translate([35,0,4.2])cylinder(d=6,h=8);
translate([35-8,0,4.2])cylinder(d=6,h=8);
translate([35-16,0,4.2])cylinder(d=6,h=8);
translate([35,0,0])cylinder(d=6,h=0.8);
translate([35-8,0,0])cylinder(d=6,h=0.8);
translate([35-16,0,0])cylinder(d=6,h=0.8);

    cylinder(d=8,h=5);
 rotate([0,0,45])for(i=[0:90:360]){
    rotate([0,0,i]){translate([6,0,0])cylinder(d=2.5,h=5);translate([6,0,1.5])cylinder(d=5,h=5);}
}
    translate([-8,-8,0])cylinder(d=2.7,h=5);
    translate([8,-8,0])cylinder(d=2.7,h=5);
    translate([8,8,0])cylinder(d=2.7,h=5);
    translate([-8,8,0])cylinder(d=2.7,h=5);
}
}


